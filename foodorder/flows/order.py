"""Guided ordering: address -> restaurant -> dish -> quantity -> cart (+best coupon) -> payment -> ✅.

Also serves "my usual": the same flow, pre-filled with the exact items of a past order.
Checkout is delegated to CheckoutAgent so the human-confirmation gate and the never-retry
rule for place_food_order live in exactly one place.
"""

import re
from typing import Any

from foodorder.agents.cart_agent import CartAgent
from foodorder.agents.checkout_agent import CheckoutAgent
from foodorder.core import db
from foodorder.core.utils import find_key
from foodorder.flows.base import MAX_OPTIONS, Flow, FlowContext, dish_tokens, money
from foodorder.tools.coupons import find_best_swiggy_coupon

SWIGGY_ORDER_CAP = 1000  # Builders Club developer access caps each order at Rs 1000
MAX_MENU_PAGES = 6  # a menu page holds up to 8 categories; 6 pages covers large menus


def _clean_name(name: str) -> str:
    return re.sub(r"\s*\(Ad\)\s*$", "", name or "").strip()


def _short_address(line: str) -> str:
    line = line.split(":", 1)[-1].strip()  # Swiggy prefixes the receiver's name: "Harish.S: Ground Floor, ..."
    return line[:40]


def find_usual(user_id: int) -> dict | None:
    """The most recent Swiggy order we can rebuild exactly (has item ids)."""
    for o in db.search_orders(user_id, provider="swiggy", limit=20):
        if o.get("reorder_items") and o.get("restaurant_id"):
            return o
    return None


class OrderFlow(Flow):
    def __init__(
        self,
        ctx: FlowContext,
        dish: str | None = None,
        people: int | None = None,
        veg_only: bool | None = None,
        max_price: int | None = None,
        usual: dict | None = None,
    ):
        super().__init__(ctx)
        self.dish, self.people, self.veg_only, self.max_price, self.usual = dish, people, veg_only, max_price, usual
        self.address: dict | None = None
        self.restaurant: dict | None = None
        self.item: dict | None = None
        self._replace_ok = False
        self._pending_cart: tuple[list[dict], bool] | None = None

    def progress(self) -> str:
        parts = [f"ordering {self.dish or 'their usual'}"]
        if self.address:
            parts.append(f"deliver to {self.address['label']} (addressId={self.address['id']})")
        if self.restaurant:
            parts.append(f"restaurant {self.restaurant['name']} (restaurantId={self.restaurant['id']})")
        if self.item:
            parts.append(f"dish {self.item['name']} (menu_item_id={self.item['id']}, Rs{self.item.get('price')})")
        if self._options:
            parts.append("buttons shown: " + " | ".join(list(self._options)[:6]))
        return "; ".join(parts)

    async def _call(self, tool: str, args: dict) -> tuple[Any, bool, str]:
        if self.ctx.trace:
            await self.ctx.trace(f"[flow] → {tool}({args})"[:200])
        text, structured, is_error = await self.ctx.hub.call("swiggy", tool, args)
        return structured, is_error, text

    async def _stop(self, message: str, summary: str) -> None:
        self.finish(summary)
        await self.ctx.say(message)

    # ---------- start ----------

    async def start(self) -> None:
        if self.usual:
            u = self.usual
            await self.ask(
                f"Your usual: {', '.join(u['items']) or 'your last order'} from {u['restaurant_name']} "
                f"({money(u.get('total'))} last time). Order it again?",
                [("🔁 Yes, order it", True), ("✨ Something else", False)],
                self._on_usual,
            )
        else:
            await self._ask_address()

    async def _on_usual(self, yes: bool) -> None:
        if not yes:
            await self._stop("Sure! What are you craving? 🍽️", "User didn't want their usual order.")
            return
        self.restaurant = {"id": str(self.usual["restaurant_id"]), "name": self.usual["restaurant_name"]}
        await self._ask_address()

    # ---------- address ----------

    async def _ask_address(self) -> None:
        data, err, _ = await self._call("get_addresses", {})
        raw = find_key(data, "addresses") or []
        if err or not raw:
            await self._stop("I couldn't load your Swiggy addresses. Add one in the Swiggy app, then try again.",
                             "Failed: no Swiggy addresses.")
            return
        addresses = [
            {"id": a["id"], "label": a.get("addressTag") or a.get("addressCategory") or "Address",
             "line": a.get("addressLine") or ""}
            for a in raw
        ]
        preferred = (db.get_preferences(self.ctx.user_id).get("default_address") or "").lower()
        chosen = next((a for a in addresses if preferred and a["label"].lower() == preferred), None)
        if chosen or len(addresses) == 1:
            await self._on_address(chosen or addresses[0])
            return
        lead = f"{self.dish.capitalize()}" + (f" for {self.people}" if self.people else "") + " 🍽️ " if self.dish else ""
        await self.ask(
            f"{lead}Where should I deliver?",
            [(f"{a['label']} · {_short_address(a['line'])}", a) for a in addresses[:MAX_OPTIONS]],
            self._on_address,
        )

    async def _on_address(self, address: dict) -> None:
        self.address = address
        if self.usual:
            await self._build_cart(self.usual["reorder_items"], needs_agent=False)
        elif not self.dish:
            await self._stop("What are you craving? 🍽️", "Asked the user which dish they want.")
        else:
            await self._ask_restaurant()

    # ---------- restaurant ----------

    async def _ask_restaurant(self) -> None:
        data, err, _ = await self._call("search_restaurants", {"addressId": self.address["id"], "query": self.dish})
        found = [r for r in (find_key(data, "restaurants") or []) if str(r.get("availabilityStatus", "")).upper() == "OPEN"]
        if err or not found:
            await self._stop(f"No open restaurants near {self.address['label']} for {self.dish} right now 😕 Try another dish?",
                             f"No open restaurants for {self.dish}.")
            return
        # Balance quality and speed: 0.1★ is worth ~1 minute of delivery time.
        found.sort(key=lambda r: -(float(r.get("avgRating") or 0) * 10 - int(r.get("deliveryTimeMinutes") or 60) / 6))
        options = [
            (f"{_clean_name(r['name'])} · {r.get('avgRating', '–')}★ · {r.get('deliveryTimeMinutes', '?')} min · "
             f"{str(r.get('costForTwo', '')).replace(' for two', '/2')}", r)
            for r in found[:MAX_OPTIONS]
        ]
        await self.ask(f"Top open spots for {self.dish} near {self.address['label']}:", options, self._on_restaurant)

    async def _on_restaurant(self, r: dict) -> None:
        self.restaurant = {"id": str(r["id"]), "name": _clean_name(r["name"])}
        await self._ask_item()

    # ---------- dish ----------

    async def _menu(self) -> list[dict]:
        items, seen = [], set()
        for page in range(1, MAX_MENU_PAGES + 1):
            data, err, _ = await self._call(
                "get_restaurant_menu",
                {"addressId": self.address["id"], "restaurantId": self.restaurant["id"], "page": page, "pageSize": 8},
            )
            if err or not data:
                break
            for category in data.get("categories", []):
                for it in category.get("items", []):
                    if it.get("id") not in seen:  # bestsellers repeat across categories
                        seen.add(it.get("id"))
                        items.append(it)
            if not data.get("hasMore"):
                break
        return items

    async def _ask_item(self) -> None:
        menu = [i for i in await self._menu() if i.get("inStock", 1)]
        if self.veg_only:
            menu = [i for i in menu if i.get("isVeg")]
        if self.max_price:
            menu = [i for i in menu if (i.get("price") or 0) <= self.max_price]
        tokens = dish_tokens(self.dish or "")
        exact = [i for i in menu if tokens and all(t in i["name"].lower() for t in tokens)]
        partial = [i for i in menu if tokens and any(t in i["name"].lower() for t in tokens)]
        matched = exact or partial
        header = (f"{self.restaurant['name']}: which one?" if exact
                  else f"No exact {self.dish} at {self.restaurant['name']}. Closest matches:")
        if not matched:
            matched = [i for i in menu if i.get("isBestseller")] or menu
            header = f"No {self.dish} at {self.restaurant['name']} 😕 Their popular dishes:"
        if not matched:
            await self._stop("I couldn't load that menu right now. Try another restaurant?", "Menu failed to load.")
            return
        if len(exact) == 1:  # one obvious match: skip a pointless single-button question
            await self._on_item(exact[0])
            return
        matched.sort(key=lambda i: (bool(i.get("isBestseller")), float(i.get("rating") or 0)), reverse=True)
        options = [(f"{i['name']} · {money(i.get('price'))}{' 🌱' if i.get('isVeg') else ''}", i) for i in matched[:MAX_OPTIONS]]
        await self.ask(header, options, self._on_item)

    async def _on_item(self, item: dict) -> None:
        self.item = item
        base = self.people or 1
        quantities = sorted({1, base, base + 1} if base > 1 else {1, 2, 3})[:4]
        await self.ask(
            f"How many {item['name']}?" + (f" (you said {self.people} people)" if self.people else ""),
            [(f"{q} × {item['name']} · {money(q * (item.get('price') or 0))}", q) for q in quantities],
            self._on_qty,
        )

    async def _on_qty(self, qty: int) -> None:
        needs_agent = bool(self.item.get("hasVariants") or self.item.get("hasAddons"))
        await self._build_cart([{"menu_item_id": str(self.item["id"]), "quantity": qty}], needs_agent)

    # ---------- cart ----------

    async def _build_cart(self, cart_items: list[dict], needs_agent: bool) -> None:
        data, _, _ = await self._call("get_food_cart", {"addressId": self.address["id"]})
        existing = find_key(data, "items") or []
        if existing and not self._replace_ok:
            names = ", ".join(f"{i.get('quantity')} × {i.get('name')}" for i in existing[:3])
            self._pending_cart = (cart_items, needs_agent)
            await self.ask(f"Your Swiggy cart already has {names}. Replace it?",
                           [("🔄 Replace it", True), ("✋ Keep my cart", False)], self._on_replace)
            return

        if needs_agent:  # variants/add-ons: let the cart agent pick valid required options
            item = self.item
            task = (f"restaurantId={self.restaurant['id']} addressId={self.address['id']}\n"
                    f"Add {cart_items[0]['quantity']} x '{item['name']}' (menu_item_id {item['id']}) from "
                    f"{self.restaurant['name']}. It has variants/add-ons: choose the default or cheapest required "
                    "options and no optional add-ons. Then apply the best coupon.")
            await CartAgent(self.ctx.client, self.ctx.hub, self.ctx.confirm, trace=self.ctx.trace).run(task)
        else:
            _, err, text = await self._call("update_food_cart", {
                "restaurantId": self.restaurant["id"], "restaurantName": self.restaurant["name"],
                "addressId": self.address["id"], "cartItems": cart_items,
            })
            if err:
                await self._stop(f"Swiggy couldn't add that to your cart: {text[:200]}", "Cart update failed.")
                return
            await find_best_swiggy_coupon(self.ctx.hub, self.address["id"], self.restaurant["id"])
        await self._review_and_pay()

    async def _on_replace(self, replace: bool) -> None:
        if not replace:
            await self._stop("OK, I left your cart as it is.", "User kept their existing Swiggy cart.")
            return
        self._replace_ok = True
        await self._call("flush_food_cart", {})
        await self._build_cart(*self._pending_cart)

    # ---------- review + payment ----------

    async def _review_and_pay(self) -> None:
        data, _, _ = await self._call("get_food_cart", {"addressId": self.address["id"], "restaurantName": self.restaurant["name"]})
        items = find_key(data, "items") or []
        if not items:
            await self._stop("Something went wrong building your cart. Please try again.", "Cart came back empty.")
            return
        pricing, offers = find_key(data, "pricing") or {}, find_key(data, "offers") or {}
        lines = [f"🛒 {self.restaurant['name']}"]
        lines += [f"{i.get('quantity')} × {i.get('name')} · {money(i.get('final_price') or i.get('total'))}" for i in items]
        if offers.get("coupon_applied") and (offers.get("coupon_discount") or 0) > 0:
            lines.append(f"🏷️ {offers['coupon_applied']} applied: −{money(offers['coupon_discount'])}")
        lines.append(f"Delivery {money(pricing.get('delivery_charge'))} · Taxes {money(pricing.get('taxes_and_charges'))}")
        to_pay = pricing.get("to_pay")
        lines.append(f"**Total: {money(to_pay)}** · to {self.address['label']}")
        budget = db.get_preferences(self.ctx.user_id).get("monthly_budget_inr")
        if budget and str(budget).isdigit():
            left = int(budget) - db.spending(self.ctx.user_id, 30)["total_spent"]
            lines.append(f"Budget left this month: {money(left)}")
        if to_pay and float(to_pay) > SWIGGY_ORDER_CAP:
            await self._stop("\n".join(lines) + f"\n\n⚠️ Swiggy caps orders from apps like this at {money(SWIGGY_ORDER_CAP)}. "
                             "Try fewer items?", "Cart is over the Rs 1000 cap.")
            return

        pay, _, _ = await self._call("get_payment_options", {"addressId": self.address["id"]})
        options: list[tuple[str, Any]] = []
        cod = (pay or {}).get("cod") or {}
        if cod.get("available"):
            options.append(("💵 Cash on delivery", {"paymentMethod": cod.get("id") or "COD"}))
        for m in (((pay or {}).get("platforms") or {}).get("mobile") or {}).get("methods", [])[:3]:
            options.append((f"📱 {m.get('displayName')} (UPI)", {"paymentMethod": "UPI", "intentApp": m.get("id")}))
        wallet = (pay or {}).get("swiggyMoney") or {}
        if wallet.get("available"):
            options.append(("👛 Swiggy Money", {"paymentMethod": wallet.get("id") or "SwiggyPay"}))
        options.append(("✋ Not now", None))
        await self.ask("\n".join(lines) + "\n\nHow would you like to pay?", options, self._on_payment)

    async def _on_payment(self, pay: dict | None) -> None:
        name = self.restaurant["name"]
        if pay is None:
            await self._stop("No problem, your cart is saved in Swiggy. Just say \"checkout\" when you're ready.",
                             f"User built a cart at {name} but hasn't ordered yet.")
            return
        task = (f"addressId={self.address['id']} paymentMethod={pay['paymentMethod']}"
                + (f" intentApp={pay['intentApp']}" if pay.get("intentApp") else "")
                + "\nThe cart is already built and the user chose this payment method. Place the order now.")
        result = await CheckoutAgent(self.ctx.client, self.ctx.hub, self.ctx.user_id, self.ctx.confirm,
                                     trace=self.ctx.trace).run(task, address_line=self.address["line"],
                                                               restaurant=self.restaurant)
        self.finish(f"Checkout at {name} via {pay['paymentMethod']}: {result[:300]}")
        if result:
            await self.ctx.say(result)
