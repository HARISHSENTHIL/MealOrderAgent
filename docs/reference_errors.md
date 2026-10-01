# Error codes

> How Swiggy MCP tools report failures, and how to react to each class of error.

## What the server emits today

All tools return failure responses in a uniform envelope:

```json
{
  "success": false,
  "error": {
    "message": "human-readable description",
    "reportLink": "https://...",
    "reportHint": "Run report_error to share diagnostics"
  }
}
```

- `message` - always present.
- `reportLink` / `reportHint` - optional, surfaced when the server has captured a diagnostic bundle the caller can share with the Builders team.

Auth failures are additionally reported via JSON-RPC error codes at the transport layer (`-32001` for unauthenticated/expired sessions, `-32603` for unexpected internal failures). Treat the HTTP status code and JSON-RPC code as secondary signals; the primary contract is the `error.message` string.

## How to classify errors today

Until the symbolic code registry below ships, classify by `error.message` prefix and HTTP status. The canonical buckets:

| Bucket | How to detect | React |
| --- | --- | --- |
| Auth failure | HTTP 401 or JSON-RPC `-32001` | Re-run the OAuth flow |
| Bad input | HTTP 400 with message starting `Invalid ...` / `Missing ...` | Fix the arguments; do not retry |
| Upstream timeout | HTTP 504 or message containing `timeout` | Exponential backoff, max 5 retries |
| Upstream error | HTTP 502/503 | Exponential backoff, max 5 retries |
| Domain failure | HTTP 200 with `success: false` | Read `message`; most are terminal (out of stock, slot gone, restaurant closed) - surface to the user, do not retry |
| Internal error | HTTP 500 or JSON-RPC `-32603` | Exponential backoff once; escalate via `report_error` if it persists |

For every failure, `report_error` is available on each server to generate a shareable diagnostic link.

## Retry strategy

Exponential backoff with jitter. Start at 500ms, double up to 8s, cap at 5 retries. See [Ship to production](/docs/build/ship-to-production.md) for the full pattern and per-tool idempotency guarantees.

## Roadmap: symbolic code registry

A stable `error.code` field is planned. Once it ships, the server will populate the following codes; agents can then branch on `error.code` instead of parsing messages. **None of these are emitted today** - rely on the message/HTTP-status buckets above.

### Core codes (planned)

| Code | Meaning | HTTP |
| --- | --- | --- |
| `UNAUTHENTICATED` | No or invalid session credentials | 401 |
| `TOKEN_EXPIRED` | Access token past its expiry | 401 |
| `SESSION_REVOKED` | Session invalidated | 419 |
| `INSUFFICIENT_SCOPE` | Need broader OAuth scope | 403 |
| `RATE_LIMITED` | Too many requests | 429 |
| `VALIDATION_ERROR` | Input failed schema check | 400 |
| `NOT_FOUND` | Resource doesn't exist | 404 |
| `UPSTREAM_TIMEOUT` | Swiggy upstream slow | 504 |
| `UPSTREAM_ERROR` | Swiggy upstream failure | 502 |
| `INTERNAL_ERROR` | Unexpected server-side failure | 500 |

### Domain codes (planned)

- **Instamart**: `ITEM_OUT_OF_STOCK`, `CART_EXPIRED`, `ADDRESS_NOT_SERVICEABLE`, `MIN_ORDER_NOT_MET`.
- **Food**: `RESTAURANT_CLOSED`, `ITEM_UNAVAILABLE`, `COUPON_INVALID`, `COUPON_NOT_APPLICABLE`, `COUPON_REQUIRES_ONLINE_PAYMENT`.
- **Dineout**: `SLOT_UNAVAILABLE`, `RESTAURANT_NOT_BOOKABLE`, `BOOKING_WINDOW_CLOSED`.

When the registry ships, the `code` field will be added to `error` without changing the rest of the envelope - agents that already parse `message` keep working.
