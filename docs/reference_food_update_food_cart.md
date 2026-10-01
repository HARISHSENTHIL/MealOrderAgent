# update_food_cart

Add items to food delivery cart or update cart contents. PRIMARY FOOD DELIVERY SERVICE - Use this when user wants to add food items, dishes, or meals to their delivery cart. Swiggy Food delivery. Supports variants, variantsV2, and addons for customizing menu items. CRITICAL: Each menu item uses EITHER "variants" OR "variantsV2" format (check search_menu response) - use the SAME format that the item has, never both fields. IMPORTANT: Addon availability depends on variant selection - some addons are only valid for specific variant combinations. After choosing the variant for an item, check the cart response for valid_addons to see which addons are actually available. NOT for groceries or restaurant reservations.

⚠️ NO UI: This tool does NOT render any UI or cart UI. The user CANNOT see the cart after this call. You MUST follow up by calling get_food_cart immediately to show the updated cart to the user. Do NOT say "your cart is shown above" or "cart reflected above" — there is nothing to see until you call get_food_cart.

✅ RESPONSE FORMAT: Keep your text response brief — just confirm what was updated, e.g. "Added 2x Chicken Biryani to your cart." Then immediately call get_food_cart.

💰 COUPON NOTE: The response may include offers.coupon_applied with coupon_discount=0 — this means the coupon is auto-suggested (best available) but NOT actually applied. Do NOT tell the user a coupon is "applied" unless coupon_discount &gt; 0. Only mention savings if there is an actual discount amount.

IMPORTANT — QUANTITY CHANGES FOR CUSTOMIZED ITEMS: When user taps +/- or asks to change quantity of an item that has addons or variants:
(1) Do NOT silently replicate the same addons for the new quantity.
(2) ASK the user: "Would you like the same add-ons (e.g. Extra Raita, Salan) for the additional item, or different ones?"
(3) Also briefly mention other available addons they haven't picked yet — e.g. "You can also add Gulab Jamun or Extra Gravy."
(4) Only after the user confirms, call update_food_cart with the chosen customization.
For items WITHOUT addons/variants, quantity changes can be applied directly without asking.

## Example

**TypeScript**
```ts
const result = await client.callTool({
  name: "update_food_cart",
  arguments: {
    restaurantId: "rest_42",
    cartItems: [],
    addressId: "addr_01HXYZ",
  },
});
```

**Python**
```py
result = await session.call_tool(
  "update_food_cart",
  arguments={
    "restaurantId": "rest_42",
    "cartItems": [],
    "addressId": "addr_01HXYZ",
  },
)
```

**curl**
```bash
curl -X POST https://mcp.swiggy.com/food \
  -H "Authorization: Bearer $SWIGGY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "update_food_cart",
      "arguments": {
    "restaurantId": "rest_42",
    "cartItems": [],
    "addressId": "addr_01HXYZ"
      }
    },
    "id": 1
  }'
```

## Parameters

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `restaurantId` | `string` | **yes** | Restaurant ID for the cart |
| `cartItems` | `object[]` | **yes** | Array of items to add to cart with their customizations |
| `addressId` | `string` | **yes** | Address ID to get accurate delivery charges based on location. |
| `restaurantName` | `string` | no | Restaurant name from search_restaurants or search_menu results. Pass this so the cart view can display the restaurant name (the cart API does not always return it). |
| `cutleryOptIn` | `boolean` | no | True to request cutlery, false to skip. Omit to leave preference unchanged. |

Session credentials (user identity, access token) are supplied automatically by the authenticated MCP session - you do not pass them in the tool call. See [Authenticate](/docs/start/authenticate.md).

## Response

All Swiggy MCP tools return:

```json
{
  "success": true,
  "data": { /* tool-specific payload */ },
  "message": "optional human-readable message"
}
```

On failure:

```json
{
  "success": false,
  "error": { "message": "description of what went wrong" }
}
```

See [Error codes](/docs/reference/errors.md) for the full catalogue.

### Output schema

```ts
data: {
  data?: {
    cart_id?: string;
    result?: string;
    restaurant?: FoodCartRestaurant | null;
    items?: FoodCartItem[];
    item_count?: number;
    pricing?: FoodCartPricing;
    offers?: FoodCartOffers;
  };
  statusCode?: number;
  statusMessage?: string;
}

type FoodCartRestaurant = {
  id?: string;
  name?: string;
  area?: string;
  deliverySubtitle?: string;
}

type FoodCartItem = {
  menu_item_id: string;
  name: string;
  imageUrl?: string;
  quantity: number;
  is_veg?: boolean | string | number;
  subtotal: number;
  total: number;
  final_price: number;
  in_stock?: boolean;
  variants?: FoodCartSelection[];
  addons?: FoodCartAddon[];
  valid_addons?: FoodCartAddonGroup[];
}

type FoodCartSelection = {
  id?: string;
  name?: string;
  group_id?: string;
  groupId?: string;
  variation_id?: string;
  variationId?: string;
  price?: number;
}

type FoodCartAddon = FoodCartSelection & {
  quantity?: number;
}

type FoodCartAddonGroup = {
  group_id?: string;
  groupId?: string;
  name?: string;
  minAddons?: number;
  maxAddons?: number;
  choices?: FoodCartAddon[];
  addons?: FoodCartAddon[];
}

type FoodCartPricing = {
  item_total: number;
  delivery_charge: number;
  delivery_charge_strikeoff?: number;
  taxes_and_charges: number;
  to_pay: number;
}

type FoodCartOffers = {
  coupon_applied?: string | null;
  coupon_discount?: number;
  free_delivery_applied?: boolean;
}
```

The cart payload is the live Food cart response after applying the requested item changes.

### Schema notes

- `menu_item_id`: Food menu item identifier used by `update_food_cart`. It is different from display name and must be copied exactly from menu/search/cart responses.
- `variation_id` / `variationId`: selected Food item variant option, such as size, preparation, or portion. Send it back with its matching customization group ID when adding or updating a customized Food item.
- `group_id` / `groupId`: customization group that a variant or addon belongs to. Keep the group and choice IDs paired exactly as returned; mixing groups can make cart updates fail or select the wrong customization.
- `valid_addons`: addon groups allowed for the item after its current variant selection. Prefer this over the broader menu addon list before offering add-ons to the user.
- `minAddons` / `maxAddons`: addon selection constraints for that group. Positive maximum values limit how many choices can be selected; minimum values mean the user must pick at least that many.
- `cart_id`: server-side cart reference for the current authenticated session. Use it only for the immediate follow-up flow; refresh the cart if the user changes items, address, slot, or payment path.
- `item_total` / `to_pay`: payable/order total fields. Show these as live values and refresh the cart or order state before final placement if anything changes.
- `delivery_charge` / `taxes_and_charges`: component charge fields. Use the final payable total for checkout decisions rather than summing components yourself.
- `coupon_applied` / `coupon_discount`: coupon visibility/application fields. Treat a coupon as applied only when the returned cart shows an applied coupon/code and a positive discount where available.
- `statusCode` / `statusMessage`: service state fields. Prefer accompanying messages/terminal flags and refresh status before taking irreversible actions.
- `price` / `final_price` / `subtotal`: item-level price fields. They may differ before and after coupons, variants, add-ons, or stock updates; use cart/order totals for checkout.
- Fields marked optional may be omitted depending on user state, cart/order state, and live Swiggy availability.
- Use returned identifiers and enum values exactly as provided; do not invent fallback IDs, status values, payment methods, or timestamps.

## Details

| Field | Value |
| --- | --- |
| **Name** | `update_food_cart` |
| **MCP Server** | [Food](/docs/reference/food.md) |
| **Endpoint** | `POST mcp.swiggy.com/food` |
| **Stage** | Cart |
| **Behaviour** | mutating |

## Next in this journey →

Continue with [`get_food_cart`](/docs/reference/food/get_food_cart.md).
