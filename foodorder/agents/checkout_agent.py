"""Checkout agent: resolves payment and places the Swiggy order.

Delegated to by the orchestrator for one task at a time. The human-confirmation gate
lives here in code (`hub.is_gated` + the `confirm` callback from the surface), not in
any prompt - so even if this agent's model hallucinates, place_food_order cannot
actually execute without the user tapping yes on the live cart/total it's shown.
"""

import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import anthropic

from foodorder.agents.harness import AgentHarness
from foodorder.agents.prompts import CHECKOUT_AGENT_SYSTEM_PROMPT
from foodorder.core import db
from foodorder.core.utils import find_key
from foodorder.providers import PROVIDERS, ProviderHub, split_tool_name

# Swiggy MCP "Payment" + "Order" stage tools (see docs/reference_food_index.md).
CHECKOUT_MCP_TOOL_NAMES = {"get_payment_options", "place_food_order", "check_payment_status", "confirm_order"}
MAX_ITERATIONS = 6

ConfirmFn = Callable[[str, str], Awaitable[bool]]  # (title, details) -> approved?
TraceFn = Callable[[str], Awaitable[None]] | None


class CheckoutAgent:
    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        hub: ProviderHub,
        user_id: int,
        confirm: ConfirmFn,
        trace: TraceFn = None,
    ):
        self.client = client
        self.hub = hub
        self.user_id = user_id
        self.confirm = confirm
        self.trace = trace
        self._address_line: str | None = None
        self._cart_snapshot: Any = None

    async def run(self, task: str, address_line: str | None = None) -> str:
        self._address_line = address_line
        tools = self.hub.claude_tools(CHECKOUT_MCP_TOOL_NAMES)
        harness = AgentHarness(
            self.client, CHECKOUT_AGENT_SYSTEM_PROMPT, tools, self._dispatch, max_iterations=MAX_ITERATIONS
        )
        result = await harness.run([{"role": "user", "content": task}])
        return result.final_text

    async def _dispatch(self, name: str, args: dict) -> tuple[str, bool]:
        if self.trace:
            await self.trace(f"[checkout] → {name}({json.dumps(args, ensure_ascii=False)[:160]})")
        parsed = split_tool_name(name)
        if not parsed:
            return f"Unknown tool {name}", True
        provider, tool = parsed

        if self.hub.is_gated(provider, tool):
            title, details = await self._confirmation_text(provider, tool, args)
            if not await self.confirm(title, details):
                return "The user declined this action in the confirmation prompt. Nothing was done.", True

        text, structured, is_error = await self.hub.call(provider, tool, args)
        if not is_error and tool in PROVIDERS[provider].order_tools:
            self._record_order(provider, tool, args, structured)
        return text, is_error

    async def _confirmation_text(self, provider: str, tool: str, args: dict) -> tuple[str, str]:
        label = PROVIDERS[provider].label
        if tool == "place_food_order":
            _, cart, _ = await self.hub.call(provider, "get_food_cart", {"addressId": args.get("addressId", "")})
            self._cart_snapshot = cart
            restaurant = find_key(cart, "restaurant") or {}
            lines = [f"{label} order from {restaurant.get('name', '?')}"]
            for it in find_key(cart, "items") or []:
                lines.append(f"  {it.get('quantity')} x {it.get('name')}  Rs{it.get('final_price', it.get('total'))}")
            pricing = find_key(cart, "pricing") or {}
            offers = find_key(cart, "offers") or {}
            if offers.get("coupon_applied"):
                lines.append(f"Coupon: {offers['coupon_applied']} (-Rs{offers.get('coupon_discount')})")
            lines.append(f"TOTAL TO PAY: Rs{pricing.get('to_pay', '?')}")
            lines.append(f"Payment: {args.get('paymentMethod') or 'default (Cash/COD if only option)'}")
            lines.append(f"Deliver to: {self._address_line or args.get('addressId')}")
            return f"Place this {label} order?", "\n".join(lines)
        return f"{label}: allow {tool}?", json.dumps(args, indent=2, ensure_ascii=False)

    def _record_order(self, provider: str, tool: str, args: dict, result: Any) -> None:
        """Save orders this agent places, so history builds up even where platform history is limited."""
        order_id = find_key(result, "orderId") or find_key(result, "order_id") or args.get("orderId")
        if not order_id:
            return
        cart = self._cart_snapshot or {}
        items = find_key(cart, "items") or []
        pricing = find_key(cart, "pricing") or {}
        offers = find_key(cart, "offers") or {}
        restaurant = find_key(cart, "restaurant") or {}
        record = {
            "provider_order_id": order_id,
            "restaurant_id": restaurant.get("id"),
            "restaurant_name": restaurant.get("name") or find_key(result, "restaurantName"),
            "ordered_at": None if tool == "confirm_order" else datetime.now(timezone.utc),
            "total": pricing.get("to_pay") or find_key(result, "totalAmount"),
            "item_total": pricing.get("item_total"),
            "delivery_fee": pricing.get("delivery_charge"),
            "discount": offers.get("coupon_discount"),
            "coupon": offers.get("coupon_applied"),
            "payment_method": args.get("paymentMethod"),
            "status": find_key(result, "status") or ("CONFIRMED" if tool == "confirm_order" else None),
            "reorder_items": [
                {k: it.get(k) for k in ("menu_item_id", "quantity", "variants", "addons") if it.get(k)}
                for it in items
            ]
            or None,
        }
        db.save_order(
            self.user_id,
            provider,
            record,
            [
                {
                    "name": it.get("name"),
                    "quantity": it.get("quantity"),
                    "price": it.get("final_price"),
                    "is_veg": 1 if it.get("is_veg") in (True, 1, "1", "true") else 0,
                }
                for it in items
            ],
            source="agent",
        )
