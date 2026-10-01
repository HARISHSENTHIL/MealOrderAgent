# get_payment_options

Fetch the live payment methods currently available for the cart. Use this when the user is ready to pay or asks which payment options are available.

## Usage notes

- Call when the user is ready to pay, asks what payment methods are available, or mentions UPI apps such as GPay, PhonePe, or Paytm.
- Use only the methods returned by this tool; do not invent or assume a payment method that was not returned.
- For Instamart, call this when payment is needed; do not assume the cart response contains the full live UPI payment list.
- After the user picks a method, hand off to the domain place-order tool: `checkout` for Instamart, `place_food_order` for Food, or `book_table` for Dineout.
- For UPI app payment, pass `paymentMethod="UPI"` and copy the selected method `id` into `intentApp`. For scan-QR, pass `paymentMethod="UPI"` and `generateUPIQR=true`. For Cash/COD, pass the returned Cash/COD method.
- For Swiggy Money, pass `paymentMethod="SwiggyPay"` to `place_food_order` (no `intentApp`, no `generateUPIQR`). Do not assume Swiggy Money is available — only offer it when this tool returns the `swiggyMoney` option.

## Example

**TypeScript**
```ts
const result = await client.callTool({
  name: "get_payment_options",
  arguments: {
    addressId: "addr_01HXYZ",
  },
});
```

**Python**
```py
result = await session.call_tool(
  "get_payment_options",
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
      "name": "get_payment_options",
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
| `addressId` | `string` | no | Food only: pass the same addressId you used for get_food_cart. It is echoed back so the payment picker can place the order directly. Recommended for Food UPI. |

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
data: PaymentOptionsView

type PaymentOptionsView = {
  platforms?: {
    mobile?: { groupName: string; methods: PaymentMethod[] };
    desktop?: { groupName: string; methods: PaymentMethod[] };
  };
  cod?: { available: boolean; id: string; displayName: string };
  swiggyMoney?: { available: boolean; id: string; displayName: string };
  allMethods: PaymentMethod[];
  paymentAmount?: string | null;
  addressId?: string;
  placeOrderToolName: "checkout" | "place_food_order" | "book_table";
}

type PaymentMethod = {
  id: string;
  groupName?: string;
  displayName?: string;
  kind?: "intent" | "qr";
  iconUrl?: string;
  enabled?: boolean;
}
```

This schema documents the structured payload returned by `get_payment_options`. Optional fields can vary by user state, cart state, and live Swiggy availability.

### Schema notes

- Use only the methods returned in `allMethods`; do not invent or assume a payment method that was not returned.
- `platforms.mobile.methods`: UPI app options. If the user selects one, pass `paymentMethod="UPI"` and copy the selected method `id` into `intentApp` exactly.
- `platforms.desktop.methods`: scan-QR options. If the user selects scan-QR, pass `paymentMethod="UPI"` and `generateUPIQR=true`.
- `cod`: Cash/COD option, when available.
- `swiggyMoney`: Swiggy Money wallet option, when offered (retail Food only). If the user selects it, pass `paymentMethod="SwiggyPay"` to `place_food_order` — there is no `intentApp` or `generateUPIQR`. The wallet debits inline; if the debit fails the order is not placed and nothing is charged, most often because the balance does not cover the total — tell the user to check their Swiggy Money balance in the Swiggy app, top up if it is short, then retry with another method (UPI or Cash/COD).
- NPCI compliance: do not ask the user for a UPI ID or VPA. Use only the returned UPI app or scan-QR options.
- `addressId`: stable identifier for a saved Swiggy delivery address. Use the returned ID in cart, checkout, and payment calls instead of reusing the human-readable address text.
- `allMethods`: live payment choices or selected payment fields for this cart/order. Offer only returned methods and pass selected payment IDs exactly.
- Fields marked optional may be omitted depending on user state, cart/order state, and live Swiggy availability.
- Use returned identifiers and enum values exactly as provided; do not invent fallback IDs, status values, payment methods, or timestamps.

## Details

| Field | Value |
| --- | --- |
| **Name** | `get_payment_options` |
| **MCP Server** | [Food](/docs/reference/food.md) |
| **Endpoint** | `POST mcp.swiggy.com/food` |
| **Stage** | Payment |
| **Behaviour** | read-only |

## Next in this journey →

Continue with [`place_food_order`](/docs/reference/food/place_food_order.md).
