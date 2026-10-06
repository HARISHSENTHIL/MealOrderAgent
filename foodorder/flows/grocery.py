"""Guided groceries: list -> products on Instamart (+ Zepto for the owner) -> comparison -> order.

The comparison card uses item prices from search (no carts touched). Only the platform the user
picks gets a cart; its real total (delivery, handling, taxes) is shown before payment, and the
order is placed only through `_place`, which always shows a ✅ card first.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any

from foodorder.agents.router import GroceryItem
from foodorder.core import db
from foodorder.core.auth import LoginRequired
from foodorder.core.utils import find_key
from foodorder.flows.base import MAX_OPTIONS, Flow, FlowContext, money
from foodorder.flows.matcher import Candidate, match
from foodorder.providers import PROVIDERS

log = logging.getLogger("foodorder.grocery")

MAX_CANDIDATES = 8  # per item per platform, shown to the matcher
ZEPTO_BATCH = 5
ADD_PANTRY = "__add_pantry__"  # search_multiple_products accepts at most 5 queries per call
PINCODE = re.compile(r"\b[1-9]\d{5}\b")


def _label(platform: str) -> str:
    return PROVIDERS[platform].label


def _short_address(line: str) -> str:
    return line.split(":", 1)[-1].strip()[:40]  # Swiggy prefixes the receiver's name


class GroceryFlow(Flow):
    def __init__(
        self,
        ctx: FlowContext,
        items: list[GroceryItem],
        platforms: tuple[str, ...],
        title: str | None = None,
        pantry: list[GroceryItem] | None = None,
    ):
        super().__init__(ctx)
        self.title = title  # e.g. the dish these ingredients are for
        self.pantry = list(pantry or [])  # optional basics the user can add with one tap
        self.items = items
        self.platforms = list(platforms)  # which grocery apps this user may use
        self.notes: list[str] = []
        self.address: dict | None = None  # Instamart address (also the Swiggy address)
        self.zepto_address: dict | None = None
        self.candidates: dict[str, list[list[Candidate]]] = {}
        self.picks: list = []
        self.chosen: str | None = None
        self._order: dict = {}
        self.out_of_stock: dict[tuple[str, int], str] = {}  # (platform, item index) -> product seen but unavailable

    def progress(self) -> str:
        parts = [f"grocery list: {', '.join(i.name for i in self.items)}"]
        if self.address:
            parts.append(f"deliver to {self.address['label']}")
        if self.chosen:
            parts.append(f"ordering on {_label(self.chosen)}")
        return "; ".join(parts)

    async def _call(self, platform: str, tool: str, args: dict) -> tuple[Any, bool, str]:
        if self.ctx.trace:
            await self.ctx.trace(f"[grocery] → {platform}.{tool}({args})"[:200])
        text, structured, is_error = await self.ctx.hub.call(platform, tool, args)
        return structured, is_error, text

    async def _stop(self, message: str, summary: str) -> None:
        self.finish(summary)
        await self.ctx.say(message)

    # ---------- connect ----------

    async def start(self) -> None:
        logged_in = set(db.logged_in_providers(self.ctx.user_id))
        for p in list(self.platforms):
            if p in self.ctx.hub.sessions:
                continue
            if PROVIDERS[p].token_key not in logged_in:
                self.platforms.remove(p)
                if p == "zepto":
                    self.notes.append("Zepto isn't connected (run `foodorder login zepto` on the Mac).")
                continue
            try:
                await self.ctx.hub.connect(p)
            except LoginRequired:
                self.platforms.remove(p)
                self.notes.append(f"{_label(p)} login expired.")
            except Exception as e:  # noqa: BLE001
                log.warning("connect %s failed: %s", p, e)
                self.platforms.remove(p)
                self.notes.append(f"{_label(p)} is unreachable right now.")
        if "instamart" not in self.platforms:
            await self._stop("I need your Swiggy login for Instamart groceries. " + " ".join(self.notes),
                             "Grocery: Instamart not connected.")
            return
        await self._ask_address()

    # ---------- address ----------

    async def _ask_address(self) -> None:
        data, err, _ = await self._call("instamart", "get_addresses", {})
        raw = find_key(data, "addresses") or []
        if err or not raw:
            await self._stop("I couldn't load your Swiggy addresses.", "Grocery: no addresses.")
            return
        addresses = [{"id": a["id"], "label": a.get("addressTag") or a.get("addressCategory") or "Address",
                      "line": a.get("addressLine") or ""} for a in raw]
        preferred = (db.get_preferences(self.ctx.user_id).get("default_address") or "").lower()
        chosen = next((a for a in addresses if preferred and a["label"].lower() == preferred), None)
        if chosen or len(addresses) == 1:
            await self._on_address(chosen or addresses[0])
            return
        names = ", ".join(i.name for i in self.items[:4]) + ("…" if len(self.items) > 4 else "")
        await self.ask(f"{self.title or '🛒 ' + names + '.'}\n\nWhere should it go?",
                       [(f"{a['label']} · {_short_address(a['line'])}", a) for a in addresses[:MAX_OPTIONS]],
                       self._on_address)

    async def _on_address(self, address: dict) -> None:
        self.address = address
        if "zepto" in self.platforms and not await self._set_zepto_address():
            self.platforms.remove("zepto")
        await self._search_and_compare()

    async def _set_zepto_address(self) -> bool:
        """Use the same place on Zepto: match by label, else by pincode."""
        data, err, _ = await self._call("zepto", "list_saved_addresses", {})
        saved = find_key(data, "addresses") or []
        label = self.address["label"].lower()
        pin = PINCODE.search(self.address["line"])
        match_ = next((z for z in saved if (z.get("label") or "").lower() == label), None) or next(
            (z for z in saved if pin and z.get("postalCode") == pin.group(0)), None)
        if err or not match_:
            self.notes.append(f"Zepto has no saved address matching {self.address['label']}, so only Instamart is shown.")
            return False
        _, err, _ = await self._call("zepto", "select_saved_address", {"addressId": match_["id"]})
        if err:
            self.notes.append("Zepto doesn't deliver there right now.")
            return False
        self.zepto_address = match_
        return True

    # ---------- search + compare ----------

    def _request(self, item: GroceryItem) -> str:
        return f"{item.name} {item.quantity or ''}".strip()

    async def _search_instamart(self) -> list[list[Candidate]]:
        # Sequential on purpose: Swiggy's server handles one request at a time per session (~0.7 s each,
        # measured: 10 searches take ~6.5 s at concurrency 1, 4 or 10 alike), and asks for one session per user.
        async def one(i: int, item: GroceryItem) -> list[Candidate]:
            data, err, _ = await self._call("instamart", "search_products",
                                            {"addressId": self.address["id"], "query": item.name})
            found: list[Candidate] = []
            for product in (find_key(data, "products") or []) if not err else []:
                for v in product.get("variations", [])[:2]:
                    if not v.get("isInStockAndAvailable") and _same_product(item.name, v.get("displayName", "")):
                        self.out_of_stock.setdefault(("instamart", i), v.get("displayName", ""))
                    if v.get("isInStockAndAvailable") and (v.get("price") or {}).get("offerPrice") is not None:
                        sla = v.get("sla") or {}
                        found.append(Candidate(platform="instamart", name=v.get("displayName") or product.get("displayName", ""),
                                               size=v.get("quantityDescription") or "", price=float(v["price"]["offerPrice"]),
                                               ids={"spinId": v.get("spinId"), "skuId": v.get("skuId")},
                                               eta_min=int(sla["value"]) if str(sla.get("value", "")).isdigit()
                                               and str(sla.get("unit", "min")).lower().startswith("min") else None))
            return found[:MAX_CANDIDATES]

        return [await one(i, item) for i, item in enumerate(self.items)]

    async def _search_zepto(self) -> list[list[Candidate]]:
        queries = [i.name for i in self.items]
        out: list[list[Candidate]] = []
        for start in range(0, len(queries), ZEPTO_BATCH):
            batch = queries[start:start + ZEPTO_BATCH]
            data, err, _ = await self._call("zepto", "search_multiple_products", {"queries": batch})
            sections = (find_key(data, "sections") or []) if not err else []
            for k, _query in enumerate(batch):
                products = sections[k].get("products", []) if k < len(sections) else []
                out.append([
                    Candidate(platform="zepto", name=p.get("name", ""), size=p.get("packSize") or "",
                              price=round(float(p["price"]) / 100, 2),  # Zepto prices are in paise
                              ids={"productVariantId": p.get("productVariantId"), "storeProductId": p.get("storeProductId")})
                    for p in products if not p.get("isAd") and (p.get("availableQuantity") or 0) > 0 and p.get("price")
                ][:MAX_CANDIDATES])
        return out

    async def _search_and_compare(self) -> None:
        if "instamart" in self.platforms:
            self.candidates["instamart"] = await self._search_instamart()
        if "zepto" in self.platforms:
            self.candidates["zepto"] = await self._search_zepto()
        self.picks = await match(self.ctx.client, [self._request(i) for i in self.items], self.candidates)

        # costs[p][i] = price for item i on platform p (None if not available there)
        costs: dict[str, list[float | None]] = {p: [] for p in self.platforms}
        for i in range(len(self.items)):
            for p in self.platforms:
                c = self._chosen(p, i)
                costs[p].append(c.price * self.picks[i].packs if c else None)
        compare = len([p for p in self.platforms if any(x is not None for x in costs[p])]) > 1

        lines = [f"🛒 Your list · {self.address['label']}"]
        for i, item in enumerate(self.items):
            lines.append(f"\n**{self._request(item)}**")
            available = [costs[p][i] for p in self.platforms if costs[p][i] is not None]
            cheapest = min(available) if compare and len(available) > 1 else None
            for p in self.platforms:
                c = self._chosen(p, i)
                if c:
                    packs = self.picks[i].packs
                    tick = " ✓" if cheapest is not None and costs[p][i] == cheapest and available.count(cheapest) == 1 else ""
                    lines.append(f"  {_label(p)}: {c.name} · {c.size}{f' × {packs}' if packs > 1 else ''} · "
                                 f"{money(costs[p][i])}{tick}")
                elif (p, i) in self.out_of_stock:
                    lines.append(f"  {_label(p)}: out of stock right now ({self.out_of_stock[(p, i)]})")
                else:
                    lines.append(f"  {_label(p)}: not found")

        n = len(self.items)
        totals = {p: (sum(x for x in costs[p] if x is not None), sum(x is not None for x in costs[p])) for p in self.platforms}
        ranked = sorted((p for p in self.platforms if totals[p][1]), key=lambda p: (-totals[p][1], totals[p][0]))
        if not ranked:
            await self._stop("I couldn't find those items on " + " or ".join(map(_label, self.platforms)) + " 😕",
                             "Grocery: nothing found.")
            return
        if compare:
            lines.append("\n" + self._benefits(costs))
        lines.append("\nDelivery & handling fees are added at checkout and shown before you pay.")
        lines += [f"ℹ️ {note}" for note in self.notes]
        options: list[tuple[str, Any]] = [
            (f"🛒 {_label(p)} · {money(totals[p][0])} · {totals[p][1]}/{n} items", p) for p in ranked
        ]
        if self.pantry:
            options.append((f"➕ Add pantry basics ({', '.join(i.name for i in self.pantry[:3])}…)", ADD_PANTRY))
        options.append(("✋ Not now", None))
        await self.ask("\n".join(lines), options, self._on_platform)

    def _benefits(self, costs: dict[str, list[float | None]]) -> str:
        """Plain-language verdict: who is cheaper like-for-like, by how much, and whether splitting pays."""
        a, b = self.platforms[0], self.platforms[1]
        both = [i for i in range(len(self.items)) if costs[a][i] is not None and costs[b][i] is not None]
        out = ["💡 **Which is better?**"]
        if both:
            ta, tb = sum(costs[a][i] for i in both), sum(costs[b][i] for i in both)
            if abs(ta - tb) < 1:
                out.append(f"• Same price on both for the {len(both)} items they both have ({money(ta)}).")
            else:
                cheap, dear = (a, b) if ta < tb else (b, a)
                lo, hi = min(ta, tb), max(ta, tb)
                out.append(f"• {_label(cheap)} is **{money(hi - lo)} cheaper** ({(hi - lo) / hi:.0%}) for the "
                           f"{len(both)} items both have: {money(lo)} vs {money(hi)}.")
            split = sum(min(costs[a][i], costs[b][i]) for i in both)
            extra = min(ta, tb) - split
            if extra >= 30:
                out.append(f"• Buying each item where it's cheapest saves {money(extra)} more, but means two "
                           "deliveries and two sets of fees.")
            elif extra > 0:
                out.append(f"• Splitting across both apps would save only {money(extra)}: not worth two delivery fees.")
        for p, q in ((a, b), (b, a)):
            only = [self.items[i].name for i in range(len(self.items)) if costs[p][i] is not None and costs[q][i] is None]
            if only:
                out.append(f"• Only {_label(p)} has: {', '.join(only)}.")
        etas = {p: min((c.eta_min for per in self.candidates.get(p, []) for c in per if c.eta_min), default=None)
                for p in (a, b)}
        known = {p: m for p, m in etas.items() if m}
        if known:
            out.append("• Delivery: " + " · ".join(f"{_label(p)} ~{m} min" for p, m in known.items()))
        return "\n".join(out)

    def _chosen(self, platform: str, i: int) -> Candidate | None:
        idx = getattr(self.picks[i], platform, None) if i < len(self.picks) else None
        per_item = self.candidates.get(platform)
        return per_item[i][idx] if per_item and idx is not None else None

    # ---------- cart ----------

    async def _on_platform(self, platform: str | None) -> None:
        if platform == ADD_PANTRY:
            self.items += self.pantry
            self.pantry = []
            self.candidates, self.out_of_stock = {}, {}
            await self._search_and_compare()
            return
        if platform is None:
            await self._stop("No problem. Send the list again any time.", "Grocery: user compared but didn't order.")
            return
        self.chosen = platform
        data, _, _ = await self._call(platform, "get_cart" if platform == "instamart" else "view_cart", {})
        existing = find_key(data, "items") or find_key(data, "cartItems") or []
        if existing:
            names = ", ".join(str(i.get("name") or i.get("displayName") or "item") for i in existing[:3])
            await self.ask(f"Your {_label(platform)} cart already has {names}. Replace it with this list?",
                           [("🔄 Replace it", True), ("✋ Keep my cart", False)], self._on_replace)
            return
        await self._build_cart()

    async def _on_replace(self, replace: bool) -> None:
        if not replace:
            await self._stop("OK, I left your cart as it is.", f"Grocery: kept existing {_label(self.chosen)} cart.")
            return
        await self._build_cart()

    async def _build_cart(self) -> None:
        p = self.chosen
        chosen = [(i, self._chosen(p, i)) for i in range(len(self.items))]
        chosen = [(i, c) for i, c in chosen if c]
        if p == "instamart":  # update_cart replaces the whole Instamart cart
            items = [{**{k: v for k, v in c.ids.items() if v}, "quantity": self.picks[i].packs} for i, c in chosen]
            _, err, text = await self._call(p, "update_cart", {"selectedAddressId": self.address["id"], "items": items})
        else:
            items = [{**c.ids, "quantity": self.picks[i].packs, "name": c.name} for i, c in chosen]
            _, err, text = await self._call(p, "update_cart", {"deviceId": f"foodorder-{self.ctx.user_id}",
                                                               "cartItems": items, "replaceCart": True})
        if err:
            await self._stop(f"{_label(p)} couldn't build the cart: {text[:200]}", "Grocery: cart update failed.")
            return
        self._order = {"items": [(c.name, c.size, self.picks[i].packs, c.price) for i, c in chosen]}
        await self._review_and_pay()

    # ---------- bill + payment ----------

    async def _bill(self) -> tuple[list[str], str | None]:
        """Real bill from the platform: line items + amount to pay."""
        p = self.chosen
        if p == "instamart":
            data, _, _ = await self._call(p, "get_cart", {})
            bill = find_key(data, "billBreakdown") or {}
            lines = [f"{li.get('label')}: {li.get('value')}" for li in bill.get("lineItems", []) if li.get("label")]
            to_pay = (bill.get("toPay") or {}).get("value") or find_key(data, "cartTotalAmount")
            return lines, to_pay
        data, _, text = await self._call(p, "create_order", {"confirmOrder": False,
                                                             "userAddressId": self.zepto_address["id"]})
        lines = [f"{k.replace('_', ' ')}: {v}" for k, v in _amounts(data)] or [text[:600]]
        to_pay = find_key(data, "totalAmount") or find_key(data, "grandTotal") or find_key(data, "toPay")
        return lines, to_pay

    async def _review_and_pay(self) -> None:
        bill, to_pay = await self._bill()
        self._order["to_pay"] = to_pay
        head = [f"🛒 {_label(self.chosen)} · to {self.address['label']}"]
        head += [f"{n} · {s}{f' × {k}' if k > 1 else ''}" for n, s, k, _ in self._order["items"]]
        self._order["card"] = "\n".join(head + [""] + bill + ([f"TOTAL TO PAY: {money(to_pay)}"] if to_pay else []))
        options = await self._payment_options()
        if not options:
            await self._stop(self._order["card"] + "\n\nI couldn't load payment options. Finish in the app?",
                             "Grocery: no payment options.")
            return
        await self.ask(self._order["card"] + "\n\nHow would you like to pay?", options + [("✋ Not now", None)],
                       self._on_payment)

    async def _payment_options(self) -> list[tuple[str, Any]]:
        p = self.chosen
        if p == "instamart":
            data, _, _ = await self._call(p, "get_payment_options", {"addressId": self.address["id"]})
            options: list[tuple[str, Any]] = []
            if ((data or {}).get("cod") or {}).get("available"):
                options.append(("💵 Cash on delivery", {"paymentMethod": "Cash"}))
            upi = (((data or {}).get("platforms") or {}).get("mobile") or {}).get("methods") or [
                m for m in (data or {}).get("allMethods", []) if "upi" in str(m.get("groupName", "")).lower()]
            for m in upi[:3]:
                options.append((f"📱 {m.get('displayName')} (UPI)", {"paymentMethod": "UPI", "intentApp": m.get("id")}))
            if ((data or {}).get("swiggyMoney") or {}).get("available"):
                options.append(("👛 Swiggy Money", {"paymentMethod": "SwiggyPay"}))
            return options
        data, _, text = await self._call(p, "get_payment_methods", {})
        blob = (str(data) + text).lower()
        options = []
        if "cod" in blob or "cash on delivery" in blob:
            options.append(("💵 Cash on delivery", {"tool": "create_order"}))
        options.append(("🔗 Pay online (payment link)", {"tool": "create_online_payment_order"}))
        if "zepto cash" in blob or "wallet" in blob:
            options.append(("👛 Zepto Cash", {"tool": "create_wallet_order"}))
        return options

    async def _on_payment(self, pay: dict | None) -> None:
        if pay is None:
            await self._stop(f"No problem, your {_label(self.chosen)} cart is saved.", "Grocery: cart built, not ordered.")
            return
        self._order["payment"] = pay
        await self._place()

    # ---------- place (the only path that orders, always behind ✅) ----------

    async def _place(self) -> None:
        p, pay = self.chosen, self._order["payment"]
        method = pay.get("paymentMethod") or pay.get("tool", "").replace("create_", "").replace("_", " ")
        details = self._order["card"] + f"\nPayment: {method}\nDeliver to: {_short_address(self.address['line'])}"
        if not await self.ctx.confirm(f"Place this {_label(p)} order?", details):
            await self._stop("❌ Cancelled. Nothing was ordered; your cart is saved.", "Grocery: user declined at ✅.")
            return
        if p == "instamart":
            args = {"addressId": self.address["id"], "paymentMethod": pay["paymentMethod"]}
            if pay.get("intentApp"):
                args["intentApp"] = pay["intentApp"]
            data, err, text = await self._call(p, "checkout", args)
        else:
            data, err, text = await self._call(p, pay["tool"], {"confirmOrder": True, "riderTip": 0,
                                                                "userAddressId": self.zepto_address["id"]})
        if err:
            # Never retried: a failed/timed-out order call may still have gone through.
            await self._stop(f"{_label(p)} reported a problem: {text[:300]}\nCheck the app before trying again.",
                             "Grocery: order call failed.")
            return
        order_id = find_key(data, "orderId") or find_key(data, "order_id")
        self._order["order_id"] = order_id
        link = find_key(data, "bridgeUrl") or find_key(data, "upiIntentUrl") or find_key(data, "paymentLink") or \
            find_key(data, "payment_url") or find_key(data, "paymentUrl")
        pending = str(find_key(data, "status") or "").upper() == "PENDING_PAYMENT" or (p == "zepto" and pay["tool"] == "create_online_payment_order")
        self._record("PENDING_PAYMENT" if pending else "PLACED")
        if pending:
            self._order["paas_id"] = find_key(data, "paasId")
            self._order["transaction_id"] = find_key(data, "transactionId")
            await self.ask(f"💳 Pay {money(self._order.get('to_pay'))} to finish: {link or text[:300]}\n"
                           "The order is placed only after payment succeeds.",
                           [("✅ I've paid", True), ("❌ Cancel", False)], self._on_paid)
            return
        await self._stop(f"✅ {_label(p)} order placed! {text[:300]}", f"Grocery order placed on {_label(p)}.")

    async def _on_paid(self, paid: bool) -> None:
        p = self.chosen
        if not paid:
            await self._stop("OK. If you don't pay, the order won't go through.", "Grocery: UPI payment abandoned.")
            return
        if p == "instamart":
            data, _, text = await self._call(p, "check_payment_status",
                                             {"paasId": self._order.get("paas_id"), "orderId": self._order.get("order_id")})
            status = str(find_key(data, "status") or text).upper()
            if "SUCCESS" in status or "PAID" in status:
                await self._call(p, "confirm_order", {"orderId": self._order["order_id"],
                                                      "paasId": self._order.get("paas_id"),
                                                      "transactionId": self._order.get("transaction_id")})
                self._record("PLACED")
                await self._stop("✅ Payment received. Your Instamart order is placed!", "Grocery order placed on Instamart.")
                return
        else:
            data, _, text = await self._call(p, "check_payment_status", {"orderId": self._order.get("order_id")})
            status = str(find_key(data, "status") or text).upper()
            if "SUCCESS" in status:
                self._record("PLACED")
                await self._stop("✅ Payment received. Your Zepto order is placed!", "Grocery order placed on Zepto.")
                return
        if "FAIL" in status or "CANCEL" in status:
            await self._stop("❌ The payment failed, so the order wasn't placed. Your cart is saved.", "Grocery: payment failed.")
            return
        await self.ask("⏳ Payment still processing. Check again in a moment?",
                       [("🔄 Check again", True), ("✋ Stop checking", False)], self._on_paid)

    def _record(self, status: str) -> None:
        if not self._order.get("order_id"):
            return
        db.save_order(
            self.ctx.user_id, self.chosen,
            {"provider_order_id": str(self._order["order_id"]), "restaurant_name": _label(self.chosen),
             "ordered_at": datetime.now(timezone.utc), "total": self._order.get("to_pay"), "status": status,
             "payment_method": self._order["payment"].get("paymentMethod") or self._order["payment"].get("tool")},
            [{"name": f"{n} ({s})", "quantity": k, "price": price * k} for n, s, k, price in self._order["items"]],
            source="agent",
        )


def _same_product(wanted: str, name: str) -> bool:
    """'mint leaves' vs 'Mint Leaves' -> True; 'mint leaves' vs 'Paan Betel Leaf Sip - Mint' -> False."""
    words = [w for w in re.findall(r"[a-z]+", wanted.lower()) if len(w) > 2]
    return bool(words) and all(w.rstrip("s") in name.lower() for w in words)


def _amounts(obj: Any, depth: int = 0) -> list[tuple[str, Any]]:
    """Bill-like fields (total/fee/tax/discount) from a response whose exact shape we don't control."""
    out: list[tuple[str, Any]] = []
    if depth > 4:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                out += _amounts(v, depth + 1)
            elif any(w in k.lower() for w in ("total", "to_pay", "topay", "payable", "fee", "tax", "discount", "charge")):
                out.append((k, v))
    elif isinstance(obj, list) and depth < 2:
        for v in obj[:1]:
            out += _amounts(v, depth + 1)
    return out
