"""Cart-agent tool: find and apply the best Swiggy coupon for the current cart."""

import json

from foodorder.core.utils import find_key
from foodorder.providers import ProviderHub

MAX_COUPONS_TO_TRY = 8  # stays well under Swiggy's 30 write calls/min

COUPON_TOOL = {
    "name": "find_best_swiggy_coupon",
    "description": (
        "For the CURRENT Swiggy cart: try every applicable coupon, compare the final payable "
        "amount (to_pay) for each, and leave the cheapest one applied. Use after the cart is built "
        "and before finishing. Returns the comparison so you can show the savings."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"addressId": {"type": "string"}, "restaurantId": {"type": "string"}},
        "required": ["addressId", "restaurantId"],
    },
}
COUPON_TOOL_NAME = COUPON_TOOL["name"]


async def find_best_swiggy_coupon(hub: ProviderHub, address_id: str, restaurant_id: str) -> dict:
    _, cart, err = await hub.call("swiggy", "get_food_cart", {"addressId": address_id})
    if err or not cart:
        return {"error": "Could not read the Swiggy cart. Build the cart first."}
    baseline = find_key(cart, "to_pay")
    current = find_key(cart, "coupon_applied")

    _, offers, err = await hub.call(
        "swiggy", "fetch_food_coupons", {"restaurantId": restaurant_id, "addressId": address_id}
    )
    if err or not offers:
        return {"error": "Could not fetch coupons.", "to_pay": baseline}
    candidates = []
    for section in find_key(offers, "coupon_sections") or []:
        for c in section.get("coupons", []):
            status = (c.get("applicabilityStatus") or "").upper()
            if c.get("applicable") or status in {"APPLICABLE", "APPLIED"}:
                code = c.get("code") or c.get("id")
                if code and code not in {x["code"] for x in candidates}:
                    candidates.append({"code": code, "title": c.get("title") or c.get("description")})

    tried = []
    for c in candidates[:MAX_COUPONS_TO_TRY]:
        _, res, err = await hub.call("swiggy", "apply_food_coupon", {"couponCode": c["code"], "addressId": address_id})
        discount = find_key(res, "coupon_discount") or 0
        tried.append({**c, "to_pay": find_key(res, "to_pay"), "discount": discount, "ok": (not err) and discount > 0})

    working = [t for t in tried if t["ok"] and t["to_pay"] is not None]
    best = min(working, key=lambda t: t["to_pay"]) if working else None
    last_ok = tried[-1]["code"] if tried and tried[-1]["ok"] else None
    if best and last_ok != best["code"]:
        await hub.call("swiggy", "apply_food_coupon", {"couponCode": best["code"], "addressId": address_id})

    return {
        "to_pay_before": baseline,
        "coupon_before": current,
        "best": best,
        "tried": tried,
        "skipped": max(0, len(candidates) - MAX_COUPONS_TO_TRY),
        "note": None if best else "No coupon reduced the total; the cart may still show the last coupon tried.",
    }


async def run_coupon_tool(hub: ProviderHub, name: str, args: dict) -> tuple[str, bool]:
    if name != COUPON_TOOL_NAME:
        return f"Unknown local tool {name}", True
    res = await find_best_swiggy_coupon(hub, args["addressId"], args["restaurantId"])
    return json.dumps(res, ensure_ascii=False, default=str), "error" in res
