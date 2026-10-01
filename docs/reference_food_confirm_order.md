# confirm_order

Complete an order after payment succeeds. For UPI flows, the place-order tool first returns `PENDING_PAYMENT`; call this only after `check_payment_status` reports a successful terminal payment and only when the order has not already been auto-confirmed.

## Usage notes

- Use this after `check_payment_status` reports a successful terminal payment and does not report `confirmed=true`.
- In widget-enabled clients, the payment widget normally auto-confirms after successful payment. Do not call this again if the status response says the order was confirmed automatically.
- Do not call this for failed or refund-initiated payment statuses.
- For Cash/COD flows that are already placed by the place-order tool, no separate payment confirmation is needed.
- Food confirm requires `orderId`, `addressId`, `lat`, and `lng` from the `place_food_order` response. `cartId` is optional but recommended. Food does not use `paasId` for confirmation.

## Example

**TypeScript**
```ts
const result = await client.callTool({
  name: "confirm_order",
  arguments: {
    orderId: "ord_42",
    addressId: "addr_01HXYZ",
    lat: 12.9716,
    lng: 77.5946,
  },
});
```

**Python**
```py
result = await session.call_tool(
  "confirm_order",
  arguments={
    "orderId": "ord_42",
    "addressId": "addr_01HXYZ",
    "lat": 12.9716,
    "lng": 77.5946,
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
      "name": "confirm_order",
      "arguments": {
    "orderId": "ord_42",
    "addressId": "addr_01HXYZ",
    "lat": 12.9716,
    "lng": 77.5946
      }
    },
    "id": 1
  }'
```

## Parameters

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `orderId` | `string` | **yes** | Order ID returned by the place-order tool. |
| `transactionId` | `string` | no | Transaction ID returned by the place-order tool (IM/Dineout only). |
| `paasId` | `string` | no | Payment transaction ID returned by the place-order tool (IM/Dineout only). |
| `addressId` | `string` | **yes for Food** | Address ID — REQUIRED for Food. Echo from place_food_order response. |
| `cartId` | `string` | no | Cart ID — optional but recommended for Food. Echo from place_food_order response. |
| `lat` | `number` | **yes for Food** | Latitude — REQUIRED for Food. Echo from place_food_order response. |
| `lng` | `number` | **yes for Food** | Longitude — REQUIRED for Food. Echo from place_food_order response. |

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
  orderId: string;
  paasId?: string;
  orderStatus?: string;
  result: "success" | "failed" | "pending" | string;
}
```

This schema documents the structured payload returned by `confirm_order`. Optional fields can vary by user state, cart state, and live Swiggy availability.

### Schema notes

- Call only after a successful terminal payment status for UPI flows, and only when the order was not already auto-confirmed.
- `result`: `success` means the order is placed, `failed` means the order could not be completed, and `pending` means the payment/order state is not ready yet.
- This call is idempotent for the same payment/order identifiers; retry only when the previous call failed due to a transient client or network issue.
- `orderStatus`: service state field. Prefer accompanying messages/terminal flags and refresh status before taking irreversible actions.
- `orderId`: order identifier for tracking, support, payment confirmation, and cancellation flows. Preserve formatting exactly as returned.
- `paasId`: payment-flow field used by Instamart and Dineout confirmation. Food confirmation does not use `paasId`; echo `addressId`, `lat`, and `lng` instead.
- `addressId` / `lat` / `lng`: required Food confirmation context. Echo these values exactly from the `place_food_order` response.
- Fields marked optional may be omitted depending on user state, cart/order state, and live Swiggy availability.
- Use returned identifiers and enum values exactly as provided; do not invent fallback IDs, status values, payment methods, or timestamps.

## Details

| Field | Value |
| --- | --- |
| **Name** | `confirm_order` |
| **MCP Server** | [Food](/docs/reference/food.md) |
| **Endpoint** | `POST mcp.swiggy.com/food` |
| **Stage** | Payment |
| **Behaviour** | mutating |

## Next in this journey →

Continue with [`track_food_order`](/docs/reference/food/track_food_order.md).
