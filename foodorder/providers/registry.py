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
    # Which stored login this server uses (Swiggy Food and Instamart share one OAuth token).
    auth_key: str = ""

    @property
    def token_key(self) -> str:
        return self.auth_key or self.name


PROVIDERS: dict[str, Provider] = {
    "swiggy": Provider(
        name="swiggy",
        label="Swiggy",
        url="https://mcp.swiggy.com/food",
        # flush_food_cart wipes items the user may have added in the app; report_error sends data to Swiggy.
        gated=frozenset({"place_food_order", "create_address", "delete_address", "flush_food_cart", "report_error"}),
        order_tools=frozenset({"place_food_order", "confirm_order"}),
    ),
    "instamart": Provider(
        name="instamart",
        label="Instamart",
        url="https://mcp.swiggy.com/im",
        gated=frozenset({"checkout", "clear_cart", "create_address", "delete_address", "report_error"}),
        order_tools=frozenset({"checkout", "confirm_order"}),
        auth_key="swiggy",
    ),
    "zepto": Provider(
        name="zepto",
        label="Zepto",
        url="https://mcp.zepto.co.in/mcp",
        # Every create_*order places a real order when confirmOrder=true (false = free preview).
        gated=frozenset({"create_order", "create_online_payment_order", "create_upi_reserve_pay_order",
                         "create_wallet_order", "add_saved_address", "update_user_name"}),
        order_tools=frozenset({"create_order", "create_online_payment_order", "create_upi_reserve_pay_order",
                               "create_wallet_order"}),
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

# Grocery (quick-commerce) servers, connected on demand by the grocery flow only.
GROCERY_PROVIDERS: tuple[str, ...] = ("instamart", "zepto")
# Zepto hasn't said whether third-party apps may serve other users, so only the owner gets it.
OWNER_ONLY_PROVIDERS: frozenset[str] = frozenset({"zepto"})
# Providers with their own login command (Instamart reuses the Swiggy login).
LOGIN_PROVIDERS: frozenset[str] = ENABLED_PROVIDERS | {"zepto"}

# Belt-and-braces: anything that looks like it spends money or edits the account is gated,
# even if a provider adds a tool we don't know about yet.
# Whole-word match so read-only tools like get_payment_options aren't caught. confirm_order is
# deliberately excluded: it only finalises a UPI order the user already approved and paid for.
RISKY_NAME = re.compile(r"(^|_)(place|checkout|pay|delete|cancel)(_|$)|create_address", re.I)
