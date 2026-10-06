"""Import past orders from each connected platform into the local database.

Known upstream limits (Oct 2026):
- Swiggy Food get_food_orders returns at most ~5 recent orders and is empty for some
  accounts (Swiggy/swiggy-mcp-server-manifest issues #50, #74). We import whatever it gives.
- Zomato exposes paginated order history; see import_zomato.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from foodorder.core import db
from foodorder.core.utils import find_key
from foodorder.providers import ProviderHub


def parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) or str(value).isdigit():
        ts = float(value)
        return datetime.fromtimestamp(ts / 1000 if ts > 1e11 else ts, tz=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    for parse in (
        datetime.fromisoformat,
        lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M:%S"),
        lambda s: datetime.strptime(s, "%d %b %Y, %I:%M %p"),
        lambda s: datetime.strptime(s, "%b %d, %Y, %I:%M %p"),
    ):
        try:
            dt = parse(text)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _swiggy_items(details: dict, summary: dict) -> list[dict]:
    items = []
    for it in find_key(details, "order_items") or []:
        items.append(
            {
                "name": it.get("name"),
                "quantity": it.get("quantity"),
                "price": it.get("final_price") or it.get("total") or it.get("price"),
                "is_veg": 1 if str(it.get("is_veg")).lower() in {"1", "true"} else 0 if it.get("is_veg") is not None else None,
            }
        )
    if not items and summary.get("orderedItems"):
        # Fallback: summary string like "2 x Chicken Biryani, 1 x Coke"
        for part in str(summary["orderedItems"]).split(","):
            qty, _, name = part.strip().partition(" x ")
            items.append({"name": name or part.strip(), "quantity": qty if name else 1})
    return items


async def import_swiggy(hub: ProviderHub, user_id: int) -> dict:
    _, addrs, err = await hub.call("swiggy", "get_addresses", {})
    if err:
        return {"error": "could not read addresses"}
    seen: dict[str, dict] = {}
    for a in find_key(addrs, "addresses") or []:
        _, res, err = await hub.call("swiggy", "get_food_orders", {"addressId": a["id"]})
        for o in (find_key(res, "orders") or []) if not err else []:
            seen.setdefault(str(o["orderId"]), o)

    new = 0
    for order_id, o in seen.items():
        _, details, _ = await hub.call("swiggy", "get_food_order_details", {"orderId": order_id})
        d = (find_key(details, "order") or {}) if details else {}
        reorder = next(
            (ac["reorderMeta"].get("orderItems") for ac in o.get("actions", []) if ac.get("reorderMeta")), None
        )
        record = {
            "provider_order_id": order_id,
            "restaurant_id": o.get("restaurantId") or d.get("restaurant_id"),
            "restaurant_name": o.get("restaurantName") or d.get("restaurant_name"),
            "cuisines": ", ".join(d.get("restaurant_cuisine") or []) or None,
            "ordered_at": parse_time(d.get("order_time") or o.get("orderedTime")),
            "total": d.get("order_total") or o.get("orderTotal"),
            "item_total": d.get("item_total"),
            "delivery_fee": d.get("order_delivery_charge"),
            "discount": d.get("order_discount"),
            "coupon": d.get("coupon_applied"),
            "payment_method": d.get("payment_method"),
            "status": o.get("orderStatus") or d.get("order_status"),
            "reorder_items": reorder,
        }
        # d may contain delivery_address / mobile: deliberately never stored.
        new += db.save_order(user_id, "swiggy", record, _swiggy_items(d, o), source="import")
    return {"found": len(seen), "new": new}


IST = ZoneInfo("Asia/Kolkata")
ZOMATO_FIRST_YEAR = 2015


def _zomato_time(text: str, year: int) -> datetime | None:
    """Zomato dates have no year ("03 Aug, 4:19PM"); the year comes from the date-range query."""
    for fmt in ("%d %b, %I:%M%p", "%d %b, %I:%M %p", "%d %b %Y, %I:%M%p"):
        try:
            dt = datetime.strptime(f"{text.strip()}", fmt)
            return dt.replace(year=year if "%Y" not in fmt else dt.year, tzinfo=IST)
        except ValueError:
            continue
    return None


def _save_zomato_order(user_id: int, o: dict, year: int) -> bool:
    items = [
        {
            "name": it.get("name"),
            "quantity": it.get("quantity"),
            "is_veg": {"veg": 1, "non-veg": 0}.get(str(it.get("dietary_tag")).lower()),
        }
        for it in o.get("catalogue_items") or []
    ]
    record = {
        "provider_order_id": o["order_id"],
        "restaurant_id": o.get("res_id"),
        "restaurant_name": o.get("res_name"),
        "ordered_at": _zomato_time(o.get("payment_date") or "", year),
        "total": o.get("payment_amount"),
        "status": o.get("payment_status"),
    }
    return db.save_order(user_id, "zomato", record, items, source="import")


async def _zomato_history(hub: ProviderHub, address_id: str, start: str, end: str) -> tuple[list[dict], bool]:
    _, res, err = await hub.call(
        "zomato", "get_order_history", {"address_id": address_id, "start_date": start, "end_date": end}
    )
    if err:
        return [], False
    return find_key(res, "order_history_items") or [], bool(find_key(res, "has_more"))


async def import_zomato(hub: ProviderHub, user_id: int) -> dict:
    """Zomato history is account-wide, but the API needs an address id, pages only via date
    ranges, and its dates omit the year. Query one calendar year at a time (month by month if
    a year overflows one page): that recovers the year and works around the per-query cap."""
    _, addrs, err = await hub.call("zomato", "get_saved_addresses_for_user", {})
    address_list = find_key(addrs, "addresses") or []
    if err or not address_list:
        return {"error": "no saved Zomato address to query history with"}
    address_id = str(address_list[0]["address_id"])

    seen: set[str] = set()
    new = 0
    for year in range(datetime.now(IST).year, ZOMATO_FIRST_YEAR - 1, -1):
        orders, has_more = await _zomato_history(hub, address_id, f"{year}-01-01", f"{year}-12-31")
        if has_more:
            for month in range(1, 13):
                last_day = (datetime(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
                month_orders, _ = await _zomato_history(
                    hub, address_id, f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day}"
                )
                orders += month_orders
        for o in orders:
            if o["order_id"] not in seen:
                seen.add(o["order_id"])
                new += _save_zomato_order(user_id, o, year)
    return {"found": len(seen), "new": new}


IMPORTERS = {"swiggy": import_swiggy, "zomato": import_zomato}


async def import_all(hub: ProviderHub, user_id: int) -> dict:
    return {p: await IMPORTERS[p](hub, user_id) for p in hub.sessions}
