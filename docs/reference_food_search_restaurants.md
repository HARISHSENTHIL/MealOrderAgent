# search_restaurants

> Search and order food from restaurants for delivery. PRIMARY FOOD DELIVERY SERVICE - Use this when user wants to order food, get food delivered, or search restaurants for delivery. Swiggy Food delive...

Search and order food from restaurants for delivery. PRIMARY FOOD DELIVERY SERVICE - Use this when user wants to order food, get food delivered, or search restaurants for delivery. Swiggy Food delivery service. Use the preferred addressId from get_addresses. NOT for restaurant reservations or dine-out.

## Example

**TypeScript**
```ts
const result = await client.callTool({
  name: "search_restaurants",
  arguments: {
    addressId: "addr_01HXYZ",
    query: "biryani",
  },
});
```

**Python**
```py
result = await session.call_tool(
  "search_restaurants",
  arguments={
    "addressId": "addr_01HXYZ",
    "query": "biryani",
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
      "name": "search_restaurants",
      "arguments": {
    "addressId": "addr_01HXYZ",
    "query": "biryani"
      }
    },
    "id": 1
  }'
```

## Parameters

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `addressId` | `string` | **yes** | Address ID from get_addresses tool |
| `query` | `string` | **yes** | Search query (restaurant name or cuisine) |
| `offset` | `number` | no | Pagination offset. Use nextOffset from previous response to load more results. Default: 0. |
| `collection` | `"EATRIGHT" \| "BOLT" \| "STORE_99"` | no | Optional Swiggy storefront collection to scope results to. Map the user's **intent** to a collection (users rarely name the storefront directly). Set exactly one when the intent clearly matches, otherwise omit. `EATRIGHT` — healthy / high-protein / low-calorie / diet food. `BOLT` — ultra-fast ~10-minute delivery. `STORE_99` — budget food around ₹99. |

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
  restaurants: Array<{
    id?: string;
    name: string;
    cuisines: string[];
    avgRating?: number;
    totalRatings?: string;
    costForTwo?: string;
    areaName?: string;
    distanceKm?: number;
    deliveryTimeMinutes?: number;
    deliveryTimeRange?: string;
    veg?: boolean;
    offer?: string;
    imageUrl?: string;
    availabilityStatus?: string;
    nextOpenTime?: string;
  }>;
  dishes: Array<{
    id?: string;
    name: string;
    price?: number;
    isVeg?: boolean;
    description?: string;
    imageUrl?: string;
    category?: string;
    inStock?: boolean;
    restaurantId?: string;
    restaurantName?: string;
    restaurantRating?: number;
    restaurantAreaName?: string;
    deliveryTimeMinutes?: number;
  }>;
  nextOffset?: string | number;
  query: string;
  totalRestaurants?: number;
  hasMore?: boolean;
}
```

This schema documents the structured payload returned by `search_restaurants`. Optional fields can vary by user state, cart state, and live Swiggy availability.

### Schema notes

- `restaurantId`: preserve the Swiggy restaurant identifier exactly for menu, cart, and order follow-up calls.
- `nextOffset` / `hasMore`: pagination fields. Use them only to fetch or display more results from the same query/list; do not treat offsets as item IDs.
- `availabilityStatus`: only recommend restaurants with status `OPEN`.
- `inStock`: live availability fields. Refresh before checkout when an item is unavailable or quantity-capped.
- `price`, `avgRating`, `totalRatings`, and `costForTwo` are display/ranking signals, not stable identifiers.

## Details

| Field | Value |
| --- | --- |
| **Name** | `search_restaurants` |
| **MCP Server** | [Food](/docs/reference/food.md) |
| **Endpoint** | `POST mcp.swiggy.com/food` |
| **Stage** | Discover |
| **Behaviour** | read-only |

## Agent guidance

How Swiggy agents and orchestration logic use this tool. Surface these expectations in your prompts or tool-selection policies.

IMPORTANT: Each restaurant in the response includes an "availabilityStatus" field with values "OPEN", "CLOSED", or "UNAVAILABLE". Always check this status before proceeding: only recommend or add items from restaurants with availabilityStatus "OPEN". If a restaurant is "CLOSED" or "UNAVAILABLE", inform the user and suggest open alternatives from the results.

After showing results, let the user pick a restaurant before searching the menu. Do NOT automatically call search_menu - wait for the user to choose.

IMPORTANT: When user asks for more options or different dishes after seeing search_menu results, first call get_restaurant_menu to discover available menu categories at the restaurant. Then call search_menu with a different category/dish name to show fresh results. Do NOT re-run search_menu with the exact same query - it will return identical results.

DISTANCE & RELEVANCE: Results are sorted by a mix of distance, rating, and relevance. Each restaurant has a "distanceKm" field. When presenting results in text: (1) Prioritize nearby restaurants with good ratings first, (2) Always mention distance for far restaurants so the user can decide - e.g. "Biryani House (8.2 km away, ~40 min delivery)", (3) Never silently recommend a far restaurant without mentioning distance and expected delivery time.

GENERIC QUERIES: When user asks generic things like "popular restaurants", "best food", "what should I eat", "suggest something" - the search API handles natural language queries with query understanding. Search with broad cuisine terms like "biryani", "pizza", "chinese", "thali" based on meal time (lunch → thali/biryani/rice, dinner → similar, snack → rolls/momos/sandwich, late night → pizza/burger). Present a curated mix of top-rated nearby options across cuisines rather than dumping raw results.

FOOD COLLECTIONS: The `collection` parameter lets you scope results to a specific Swiggy storefront. Map the user's intent — not their exact words — to a collection:
- **EATRIGHT** — "something healthy", "low cal", "guilt-free", "diet-friendly", "high protein"
- **BOLT** — "quickest", "fastest", "in 10 mins", "ASAP", "super quick"
- **STORE_99** — "cheap", "budget", "under ₹100", "pocket-friendly"

Only one collection applies at a time. If the user's intent doesn't clearly match any collection, omit the parameter entirely for a standard search. Note: `STORE_99` returns few or no results for non-budget queries (it only lists ~₹99 items) — if results come back empty, inform the user and retry without the collection.

## Next in this journey →

Continue with [`get_restaurant_menu`](/docs/reference/food/get_restaurant_menu.md).
