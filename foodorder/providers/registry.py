"""Which food-platform MCP servers we know about, and which of their tools are risky."""

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Provider:
    name: str
    label: str
    url: str
    # Tools that spend money or change account data; always need a human "yes".
    gated: frozenset[str]
    # Tools whose success means an order was placed/confirmed; we record those orders.
    order_tools: frozenset[str] = field(default_factory=frozenset)


PROVIDERS: dict[str, Provider] = {
    "swiggy": Provider(
        name="swiggy",
        label="Swiggy",
        url="https://mcp.swiggy.com/food",
        gated=frozenset({"place_food_order", "create_address", "delete_address"}),
        order_tools=frozenset({"place_food_order", "confirm_order"}),
    ),
    "zomato": Provider(
        name="zomato",
        label="Zomato",
        url="https://mcp-server.zomato.com/mcp",
        gated=frozenset({"checkout_cart", "bind_user_number", "bind_user_number_verify_code"}),
        order_tools=frozenset({"checkout_cart"}),
    ),
}

# Hidden for now while we focus on Swiggy; the Zomato integration above is untouched.
# Re-enable by adding "zomato" back here. Note: the Cart/Checkout agents (foodorder.agents)
# are currently written Swiggy-only, so re-enabling Zomato needs work there too, not just this flag.
ENABLED_PROVIDERS: frozenset[str] = frozenset({"swiggy"})

# Belt-and-braces: anything that looks like it spends money or edits the account is gated,
# even if a provider adds a tool we don't know about yet.
# Whole-word match so read-only tools like get_payment_options aren't caught. confirm_order is
# deliberately excluded: it only finalises a UPI order the user already approved and paid for.
RISKY_NAME = re.compile(r"(^|_)(place|checkout|pay|delete|cancel)(_|$)|create_address", re.I)
