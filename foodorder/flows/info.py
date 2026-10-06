"""One-shot answers that need no conversation: order tracking, spending, order history."""

from foodorder.core import db
from foodorder.core.utils import find_key
from foodorder.flows.base import FlowContext, money


async def track_order(ctx: FlowContext) -> str:
    """Status of the user's active Swiggy order, straight from Swiggy."""
    _, data, err = await ctx.hub.call("swiggy", "get_addresses", {})
    for address in (find_key(data, "addresses") or []) if not err else []:
        _, orders, err = await ctx.hub.call("swiggy", "get_food_orders", {"addressId": address["id"], "activeOnly": True})
        active = [o for o in (find_key(orders, "orders") or []) if o.get("isActiveOrder")]
        if active:
            order = active[0]
            text, _, err = await ctx.hub.call("swiggy", "track_food_order", {"orderId": str(order["orderId"])})
            header = f"📦 {order.get('restaurantName', 'Your order')} · {order.get('orderTotal', '')}".strip(" ·")
            return f"{header}\n{text}" if not err else f"{header}\nStatus: {order.get('orderStatus', 'in progress')}"
    return "No active Swiggy orders right now. 🍽️"


def spending(ctx: FlowContext, days: int | None) -> str:
    days = days or 30
    s = db.spending(ctx.user_id, days)
    if not s["total_orders"]:
        return f"No orders recorded in the last {days} days."
    lines = [f"💰 Last {days} days: **{money(s['total_spent'])}** across {s['total_orders']} orders"]
    lines += [f"• {p.title()}: {money(v['spent'])} ({v['orders']} orders)" for p, v in s["by_provider"].items()]
    budget = db.get_preferences(ctx.user_id).get("monthly_budget_inr")
    if budget and str(budget).isdigit() and days == 30:
        lines.append(f"Budget left: {money(int(budget) - s['total_spent'])} of {money(budget)}")
    return "\n".join(lines)


def order_history(ctx: FlowContext, limit: int = 5) -> str:
    orders = db.search_orders(ctx.user_id, limit=limit)
    if not orders:
        return "No orders stored yet. Orders you place through me are saved automatically."
    lines = ["🧾 Your recent orders:"]
    for o in orders:
        when = (o.get("ordered_at") or "")[:10]
        items = ", ".join(o["items"][:2]) + ("…" if len(o["items"]) > 2 else "")
        lines.append(f"• {when} · {o.get('restaurant_name') or '?'} · {money(o.get('total'))}" + (f"\n  {items}" if items else ""))
    return "\n".join(lines)
