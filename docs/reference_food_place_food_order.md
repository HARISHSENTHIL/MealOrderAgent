# place_food_order

Place food delivery order and confirm order placement. PRIMARY FOOD DELIVERY SERVICE - Use this when user wants to place order, confirm order, or complete food delivery order. Swiggy Food delivery. Requires delivery address ID (coordinates are fetched automatically). NOT for groceries or restaurant reservations.

Payment selection: use the payment method the user selected from get_payment_options or the cart response. For UPI, pass paymentMethod="UPI" and the selected app identifier in intentApp, or set generateUPIQR=true for scan-QR. For Cash/COD, pass the cash method only when it is available.

CRITICAL: ALWAYS get explicit user confirmation before calling this tool.
1. Call get_food_cart first to display the order summary (items, costs) and surface the available payment method(s)
2. Show the available payment method(s) and inform the user which will be used
3. Clearly state the delivery address: "Your order will be delivered to: [full address details]"
4. Ask: "Do you want to proceed with placing this order to this address?"
5. Wait for clear confirmation (yes/confirm/proceed)
6. NEVER proceed without explicit user permission

⚠️ UPI PAYMENT — DO NOT ANNOUNCE SUCCESS EARLY: If the tool response has status="PENDING_PAYMENT" (UPI flow), the order is NOT placed yet — payment is still pending. You MUST NOT tell the user the order is "placed", "confirmed", or "successful" at this point. The UI shows the UPI app link / QR; the user pays in their UPI app, then the flow continues: check_payment_status (poll until SUCCESS) → confirm_order. ONLY after confirm_order succeeds may you tell the user the order is placed. Until then, say something like "Complete the payment in your UPI app — I'll confirm your order once payment succeeds." Never claim placement on a PENDING_PAYMENT response.

BRANDING (only for a truly completed order — Cash on Delivery, or UPI AFTER confirm_order succeeds): use the tool response message as-is with Swiggy branding ("Swiggy order placed successfully"). Do NOT apply this to a PENDING_PAYMENT response.

CANCELLATION: If the user asks to cancel their food order, do NOT call any tool. Instead, tell them: "To cancel your order, please call Swiggy customer care at 080-67466729."

## Example

**TypeScript**
```ts
const result = await client.callTool({
  name: "place_food_order",
  arguments: {
    addressId: "addr_01HXYZ",
  },
});
```

**Python**
```py
result = await session.call_tool(
  "place_food_order",
  arguments={
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
      "name": "place_food_order",
      "arguments": {
    "addressId": "addr_01HXYZ"
      }
    },
    "id": 1
  }'
```

## Parameters

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `addressId` | `string` | **yes** | Address ID from the user's saved addresses (coordinates will be fetched automatically) |
| `paymentMethod` | `string` | no | The payment method the user selected (e.g. "UPI" or "Cash"). For UPI payments, first call get_payment_options and pass the method the user chose. For Cash/COD, this may be omitted only when Cash is the only available method. |
| `intentApp` | `string` | no | Optional advanced parameter. Leave blank unless the runtime response of the preceding get_food_cart call explicitly tells you what to pass. |
| `generateUPIQR` | `boolean` | no | Optional advanced parameter. Leave blank unless the runtime response of the preceding get_food_cart call explicitly tells you to enable it. |
| `noteToRestaurant` | `string` | no | Free-form note to the restaurant preparing the order (e.g. "no onions", "less spicy"). Not for delivery partner instructions. |

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
data:
  | {
      // Cash/COD: order is placed immediately.
      orderId: string | null;
      status: string; // usually "CONFIRMED"
      normalizedStatus: "success";
      items: FoodPlacedItem[];
      restaurantName: string | null;
      restaurantAddress: string | null;
      totalAmount: number | string | null;
      estimatedDelivery: string | null;
      deliveryAddress: string | null;
    }
  | {
      // UPI: order is created but not placed until payment succeeds and confirmation runs.
      orderId: string;
      paasId: string;
      transactionId: string;
      upiIntentUrl: string;
      bridgeUrl: string;
      isQrFlow: boolean;
      pollingIntervalInMs: number;
      maxTimeToPollForInMs: number;
      paymentMethod: "UPI";
      status: "PENDING_PAYMENT";
      normalizedStatus: "pending";
      totalAmount?: number;
      restaurantName?: string | null;
      restaurantAddress?: string | null;
      deliveryAddress?: string | null;
      addressId: string;
      cartId: string | null;
      lat: number;
      lng: number;
    }

type FoodPlacedItem = {
  item_id?: string;
  name?: string;
  quantity?: string | number;
  total?: string | number;
  subtotal?: string | number;
  final_price?: string | number;
}
```

This schema documents the structured payload returned by `place_food_order`. Optional fields can vary by user state, cart state, and live Swiggy availability.

### Schema notes

- `totalAmount`: payable/order total for Food place-order responses. Show this as the live value and refresh the cart or order state before final placement if anything changes.
- `status` / `normalizedStatus`: service state fields. `PENDING_PAYMENT` / `pending` means the UPI order is not placed yet; wait for successful payment confirmation before announcing success.
- `orderId`: order identifier for tracking, support, payment confirmation, and cancellation flows. Preserve formatting exactly as returned.
- `paasId` / `transactionId` / `isQrFlow` / `paymentMethod`: payment-flow fields for UPI flows. Payment IDs are used for payment-status polling; `isQrFlow=true` means the user is expected to complete payment through a scan-QR path.
- `upiIntentUrl` / `bridgeUrl`: UPI payment links. Use `bridgeUrl` when you need to share an opaque payment link; clients that render the payment UI may use `upiIntentUrl` for UPI app launch or QR rendering.
- `pollingIntervalInMs` / `maxTimeToPollForInMs`: polling hints for status refreshes. Do not poll faster than the returned interval; stop when a terminal status is returned.
- `addressId` / `cartId` / `lat` / `lng`: Food confirmation context. Echo these values from the UPI `place_food_order` response into `check_payment_status` or `confirm_order` when your client needs to finalize explicitly.
- `restaurantAddress`: restaurant locality/area displayed on the confirmation card. This replaces older `restaurantArea` naming.
- Swiggy Money (`paymentMethod="SwiggyPay"`): a wallet that debits inline, so the order is placed immediately with `normalizedStatus="success"` — the same shape as Cash/COD, with no `paasId`, `intentApp`, or `generateUPIQR`. If the wallet debit fails the order is not placed and nothing is charged, most often because the balance does not cover the total — tell the user to check their Swiggy Money balance in the Swiggy app, top up if it is short, then retry with another method (UPI or Cash/COD). Do not retry SwiggyPay until they have topped up.
- Fields marked optional may be omitted depending on user state, cart/order state, and live Swiggy availability.
- Use returned identifiers and enum values exactly as provided; do not invent fallback IDs, status values, payment methods, or timestamps.

## Details

| Field | Value |
| --- | --- |
| **Name** | `place_food_order` |
| **MCP Server** | [Food](/docs/reference/food.md) |
| **Endpoint** | `POST mcp.swiggy.com/food` |
| **Stage** | Order |
| **Behaviour** | mutating |

## Next in this journey →

Continue with [`track_food_order`](/docs/reference/food/track_food_order.md).
