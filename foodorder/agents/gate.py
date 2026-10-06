"""Human-readable confirmation cards for gated tools (see providers.registry `gated`).

Any agent that may call a gated tool asks the user through the surface's `confirm` callback
with one of these cards first; the order-placing card lives in CheckoutAgent.
"""

import json
from collections.abc import Awaitable, Callable

from foodorder.core.utils import find_key
from foodorder.providers import PROVIDERS, ProviderHub

ConfirmFn = Callable[[str, str], Awaitable[bool]]
DECLINED = "The user declined this action in the confirmation prompt. Nothing was done."


async def describe(hub: ProviderHub, provider: str, tool: str, args: dict) -> tuple[str, str]:
    label = PROVIDERS[provider].label
    if tool in {"flush_food_cart", "clear_cart"}:
        cart_tool = "get_food_cart" if tool == "flush_food_cart" else "get_cart"
        _, cart, _ = await hub.call(provider, cart_tool, {k: v for k, v in args.items() if k == "addressId"})
        items = find_key(cart, "items") or []
        listed = "\n".join(f"  {i.get('quantity')} x {i.get('name')}" for i in items[:8]) or "  (couldn't read the cart)"
        return f"Empty your {label} cart?", f"This removes everything currently in it:\n{listed}"
    if tool == "report_error":
        ids = json.dumps(args.get("toolContext") or {}, ensure_ascii=False)
        return (f"Send an error report to {label}?",
                f"{label} will receive and log:\n  Error: {args.get('errorMessage', '')}\n  "
                f"What happened: {args.get('flowDescription', '')}\n  IDs: {ids}")
    if tool in {"create_address", "add_saved_address"}:
        return f"Add a new {label} address?", json.dumps(args, indent=2, ensure_ascii=False)
    if tool == "delete_address":
        return f"Delete a saved {label} address?", f"Address id: {args.get('addressId')}"
    return f"{label}: allow {tool}?", json.dumps(args, indent=2, ensure_ascii=False)


async def confirm_gated(hub: ProviderHub, confirm: ConfirmFn, provider: str, tool: str, args: dict) -> bool:
    """True if the tool may run: either it isn't gated, or the user approved the card."""
    if not hub.is_gated(provider, tool):
        return True
    title, details = await describe(hub, provider, tool, args)
    return await confirm(title, details)
