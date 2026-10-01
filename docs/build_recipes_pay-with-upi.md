# Pay with UPI end-to-end

> The shared UPI Payment stage - from picker to paid order to tracking - across Food, Instamart, Dineout, and Scenes.

In-chat UPI payment. This recipe picks up once the cart (or paid booking) is ready and walks the **shared Payment stage**: `get_payment_options → place-order → check_payment_status → confirm_order`. The three shared tools (`get_payment_options`, `check_payment_status`, `confirm_order`) — plus each server's own place-order tool — work across all four servers. COD is the fallback on Food, Instamart, and Dineout: when UPI isn't available for the cart, the picker offers Cash automatically. Scenes is the exception — event tickets are prepaid, so no Cash method is ever returned there.

## The flow

```
cart ready  (get_food_cart / get_cart / create_cart)
     │
     ▼
get_payment_options ─────► renders the payment picker (UPI apps + scan-QR, or Cash)
     │
     ▼
place_food_order / checkout / book_table   (paymentMethod:"UPI" + intentApp OR generateUPIQR)
     │                                       → order created in PENDING_PAYMENT (returns paasId + orderId)
     ▼
check_payment_status  ◄── the widget auto-polls; auto-finalizes on any terminal outcome
     │
     ▼
confirm_order  ─────────► PENDING_PAYMENT → PLACED (or failed)
     │
     ▼
track_food_order / track_order / get_booking_status
```

## Step 1 - Fetch payment options

```ts
const opts = await client.callTool({
  name: "get_payment_options",
  // Food only: pass the same addressId you used for get_food_cart (it's echoed to the picker)
  arguments: { addressId: home.id },
});
```

One call returns **both** device surfaces merged into a picker widget:

- `data.platforms.mobile.methods[]` - UPI apps (intent)
- `data.platforms.desktop.methods[]` - scan-QR
- `data.cod` - Cash, when available

The widget auto-detects the device and promotes the matching surface - you don't ask the user what device they're on. If UPI isn't available for the cart, `platforms` is omitted and only Cash is offered via `data.allMethods`. See [`get_payment_options`](/docs/reference/food/get_payment_options.md).

## Step 2 - Place the order with the picked method

The user taps a method in the picker; pass their choice into the place-order tool byte-for-byte:

```ts
// Mobile UPI app:
const order = await client.callTool({
  name: "place_food_order",
  arguments: {
    addressId: home.id,
    paymentMethod: "UPI",
    intentApp: picked.id,       // the method id from get_payment_options, echoed exactly
  },
});

// Desktop scan-QR: paymentMethod:"UPI" + generateUPIQR:true (no intentApp)
```

This creates the order in **`PENDING_PAYMENT`** and returns `paasId` + `orderId`. Echo them into `check_payment_status`. The `confirm_order` args differ per server (see the [contract](#per-server-contract) below): **Food** uses `orderId` + `addressId` + `lat` + `lng` (**not** `paasId`); **Instamart / Dineout / Scenes** use `orderId` + `paasId`.

## Step 3 - Wait for payment (don't babysit the poll)

`check_payment_status` is a **long-poll** (the server holds ~19s). The confirmation widget polls it automatically and auto-finalizes on any terminal outcome, so on a widget host **you do nothing here**. Only if you drive your own loop (no widget), cap it and read `data.status`:

```ts
// self-hosted clients only - the widget does this for you.
// Food: ALSO echo addressId + lat + lng, else the server can't reconcile the order and it stays pending.
const deadline = Date.now() + order.data.maxTimeToPollForInMs;   // honor the window place-order gave you
let s;
do {
  s = (await client.callTool({
    name: "check_payment_status",
    arguments: { paasId: order.data.paasId, orderId: order.data.orderId, addressId: home.id, lat: home.lat, lng: home.lng },
  })).data;
  if (s.terminal) break;
  await sleep(order.data.pollingIntervalInMs);                   // gentle — it's a ~19s long-poll
} while (Date.now() < deadline);                                 // capped — never tight-loop
```

Branch on `data.status`:

- `success` / `paid` → placed (usually already confirmed for you; `data.confirmed`)
- `failed` → don't confirm; re-show `get_payment_options` for a fresh attempt
- `cancelled` → order was cancelled (refund if already paid); tell the user, don't retry
- `cart_changed` → cart price/stock changed, so the order was NOT placed (not a payment failure); ask the user to review the cart, then place again
- `refund-initiated` → a refund is already underway; tell the user, don't retry
- `pending` → keep waiting, capped - never tight-loop (it stresses the payment cache)

See [`check_payment_status`](/docs/reference/food/check_payment_status.md).

## Step 4 - Finalize

On the widget path this is automatic. If you hit your own cap while still `pending`, call [`confirm_order`](/docs/reference/food/confirm_order.md) once to finalize (the backend marks it failed if payment is still non-terminal; a late success reconciles server-side):

```ts
await client.callTool({
  name: "confirm_order",
  // Food: orderId + addressId + lat + lng (no paasId). IM/Dineout/Scenes: orderId + paasId.
  arguments: { orderId: order.data.orderId, addressId: home.id, lat: home.lat, lng: home.lng },
});
```

## Step 5 - Track

Same as the COD journeys: [`track_food_order`](/docs/reference/food/track_food_order.md) / [`track_order`](/docs/reference/instamart/track_order.md) / [`get_booking_status`](/docs/reference/dineout/get_booking_status.md) / [`get_event_booking_status`](/docs/reference/scenes/get_event_booking_status.md).

## Non-UI (headless) clients

Everything above assumes a **widget host** — the picker and confirmation widgets render the QR (or launch the UPI app), auto-poll `check_payment_status`, and auto-confirm. **Headless clients** — terminal MCP clients, server-to-server agents, anything that can't render a widget — run the *same four tools*. They just present options as text, share a payment link, and drive the poll loop themselves.

**Both payment methods are fully supported without any UI:**

| Method | How it works headless |
| --- | --- |
| **Cash (COD)** | No payment leg at all — place with `paymentMethod:"Cash"` and you're done. The truly zero-UI path. |
| **UPI** (app intent *and* scan-QR) | The place-order response returns a ready-to-use **`bridgeUrl`** — an opaque HTTPS payment link — in **`data.bridgeUrl`** (present for *both* the app-intent and scan-QR choices, which resolve to the **same** link). Read it from `data.bridgeUrl` and share it with the user. **Opening it renders a scan-or-tap payment page** — a scannable QR plus an "Open in your UPI app" button — so the user **scans it on desktop, or taps to open their UPI app on mobile**; you don't need to render your own QR. The app-intent flow also relays the link in the response `message`; the scan-QR flow does not — so always read `data.bridgeUrl` rather than parsing the message. |

### The headless flow

```
get_payment_options ──► read data.allMethods (flat text list) ──► present as text; user picks
     │
     ▼
place-order  (paymentMethod:"UPI" + intentApp | generateUPIQR   OR   paymentMethod:"Cash")
     │   UPI → response carries: bridgeUrl, paasId, orderId, isQrFlow,
     │          pollingIntervalInMs, maxTimeToPollForInMs
     ▼
share bridgeUrl with the user   (opens a scan-or-tap QR page: scan on desktop, tap on mobile)
     │
     ▼
check_payment_status  ──► YOUR capped loop (honor maxTimeToPollForInMs; re-poll gently on pending)
     │
     ▼
confirm_order  ──► call it yourself on SUCCESS, or once at your cap if still pending
     │
     ▼
track-order
```

Three behavioural differences from the widget path: **(1)** you present `data.allMethods` as text instead of a rendered picker, **(2)** you hand the user `data.bridgeUrl` (opening it shows a scan-or-tap QR page) instead of an in-widget QR / tap-button, and **(3)** nothing auto-polls or auto-confirms — you own the `check_payment_status` cadence and the final `confirm_order`.

```ts
// 1. Options as text (no picker widget)
const opts = (await client.callTool({
  name: "get_payment_options",
  arguments: { addressId: home.id },          // Food only
})).data;
// opts.allMethods → flat list you can print; opts.cod → Cash fallback

// 2. Place the order with the user's pick (UPI shown; for Cash use paymentMethod:"Cash")
const order = (await client.callTool({
  name: "place_food_order",
  arguments: { addressId: home.id, paymentMethod: "UPI", intentApp: picked.id },
})).data;

// Cash has no payment leg — the order is already placed. Skip straight to tracking.
if (picked.paymentMethod === "Cash") {
  // → track-order; nothing more to do (no bridgeUrl, no polling).
} else {
  // 3. UPI → share the payment link (opens a scan-or-tap QR page).
  console.log(`Pay here — scan on desktop, tap on mobile: ${order.bridgeUrl}`);

  // 4. Drive your OWN capped poll — the widget isn't here to do it.
  //    Food: ALSO echo addressId + lat + lng, or the server can't reconcile the order → stuck pending.
  const deadline = Date.now() + order.maxTimeToPollForInMs;
  let s;
  do {
    s = (await client.callTool({
      name: "check_payment_status",
      arguments: { paasId: order.paasId, orderId: order.orderId, addressId: home.id, lat: home.lat, lng: home.lng },
    })).data;
    if (s.terminal) break;
    await sleep(order.pollingIntervalInMs);      // gentle — it's a ~19s long-poll
  } while (Date.now() < deadline);

  // 5. Finalize yourself
  if (s.status === "success" || s.status === "paid") {
    if (!s.confirmed) {                          // usually already confirmed server-side; confirm if not
      await client.callTool({
        name: "confirm_order",
        arguments: { orderId: order.orderId, addressId: home.id, lat: home.lat, lng: home.lng },
      });
    }
  } else if (!s.terminal) {
    // hit the cap still pending → confirm once to finalize (a late success reconciles server-side)
    await client.callTool({
      name: "confirm_order",
      arguments: { orderId: order.orderId, addressId: home.id, lat: home.lat, lng: home.lng },
    });
  }
}
```

> **Note**
>
> Headless agent prompt: when the user is ready to pay, call `get_payment_options` and present `data.allMethods` as a short text list — never ask which device they're on, never ask for a UPI ID. On a UPI pick, place the order and give the user `data.bridgeUrl` to open on their phone. Then poll `check_payment_status` every `data.pollingIntervalInMs`, capped at `data.maxTimeToPollForInMs`: on `success` the order is usually already placed, on `failed` offer `get_payment_options` again, on `refund-initiated` stop, and if you hit the cap still `pending` call `confirm_order` once. For Cash, just place with `paymentMethod:"Cash"` — no link, no polling. Cash is never offered on Scenes.

## Per-server contract

The Payment stage is shared, but each server echoes the identifiers its place-order and confirm need. Echo them from the responses - don't reconstruct them.

| Server | Place-order tool | UPI args | `confirm_order` args |
| --- | --- | --- | --- |
| **Food** | `place_food_order` | `addressId` + `paymentMethod:"UPI"` + `intentApp` / `generateUPIQR` | `orderId` + `addressId` + `lat` + `lng` |
| **Instamart** | `checkout` | `paymentMethod:"UPI"` + `intentApp` / `generateUPIQR` | `orderId` + `paasId` |
| **Dineout** | `book_table` (paid deal) | `cartKey` + `paymentMethod:"UPI"` + `intentApp` / `generateUPIQR` | `orderId` + `paasId` |
| **Scenes** | `place_event_order` | `cartKey` + `paymentMethod:"UPI"` + `intentApp` / `generateUPIQR` | `orderId` + `paasId` |

Dineout's paid path also needs `create_cart` (`DEAL_TICKET_PURCHASE`) first, which returns the `cartKey`. Scenes needs `create_event_cart` first, and only enters this stage when it returns `checkoutMode=UPI`.

## Full agent prompt

> **Note**
>
> When the user is ready to pay, call `get_payment_options` - it renders the picker; never ask which device they're on, and never ask for a UPI ID. Pass the picked method into the place-order tool exactly (`intentApp` for an app, `generateUPIQR` for desktop QR). The order is created in PENDING_PAYMENT; the widget polls `check_payment_status` and finalizes automatically, so do NOT loop it yourself. On `failed`, offer to retry via `get_payment_options`; on `refund-initiated`, tell the user a refund is underway and stop. If UPI isn't available, the picker offers Cash - use COD. On Scenes there is no Cash option, so stop and tell the user the ticket cannot be paid for right now.

## What can go wrong

- **UPI not available** → the picker shows only Cash; fall back to COD (`paymentMethod:"Cash"`).
- **Payment `failed`** → do NOT call `confirm_order`; re-show `get_payment_options` and place again (a fresh transaction on the same cart).
- **`refund-initiated`** → the money was debited and a refund has already started; tell the user and do not retry.
- **Timed out** (still `pending` at your cap) → call `confirm_order` once to finalize; a late payment success is reconciled server-side.
- **Tight-looping `check_payment_status`** → it's a long-poll; hammering it stresses the payment cache. Let the widget own the cadence, or cap your own loop.
- **NPCI compliance** → never ask the user for their UPI ID (VPA); the picker and QR handle it. UPI Collect and saved VPAs are not surfaced.
