# Rate limits

> How Swiggy MCP handles abusive traffic today, the quotas we plan to advertise, and how to request a larger allocation.

## Status today

Rate limiting is **enforced at the MCP layer**. Auth events (connection and initialization handshakes) are counted and throttled independently of tool-call volume. That means:

- You **will** see `429 Too Many Requests` from a Swiggy MCP endpoint if you exceed the quotas below.
- You **will** see `X-RateLimit-*` response headers on every successful response.
- If rate limited, the tool call surfaces as a `RATE_LIMITED` error — stop retrying immediately, apply backoff, and if blocked raise a request to [builders@swiggy.in](mailto:builders@swiggy.in).

If you're building for production traffic that will exceed the quotas below, email [builders@swiggy.in](mailto:builders@swiggy.in) **before** you launch so we can negotiate a custom ceiling.

## Active quotas

| Scope | Limit |
| --- | --- |
| Per authenticated user, per server | 70 requests / minute |
| Per authenticated user, per server (write tools) | 30 requests / minute |
| Burst (10-second window) | 2× steady-state |

Limits are keyed on the authenticated user. Enterprise integrators will get bespoke ceilings scoped at onboarding.

## Response contract

Every successful response carries:

```
X-RateLimit-Limit: 70
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1720000060
```

Throttled calls will return:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 23
```

With the standard error envelope (`error.message` populated). A symbolic `error.code` of `RATE_LIMITED` will be added once the error-code registry ships - see [errors](/docs/reference/errors.md).

## How to upgrade

Mail [builders@swiggy.in](mailto:builders@swiggy.in) with:

1. Your integration name and a contact email.
2. Expected QPS (sustained and peak) with justification.
3. Surface context - voice agent, batch jobs, chat agent all have different burst shapes.

Turnaround: typically same business day once validated. Enterprise partners get bespoke ceilings written into the contract.

## Best practices (apply today)

- **Batch where possible** - one `get_addresses` per session is plenty; don't re-fetch on every turn.
- **Cache low-churn data** - saved addresses, restaurant metadata, menu images change slowly.
- **Don't poll `track_*` faster than 10s** - delivery-partner ETA updates arrive at that cadence.
- **Back off aggressively on transient upstream errors** - exponential backoff with jitter, max 5 retries.
- **Separate user activity from background jobs** - if you run nightly analytics, talk to us at onboarding so we can carve out a bespoke ceiling and keep that traffic off your interactive budget.

## Connection & session hygiene

- **One session per user, not one per request.** Auth happens once per connection. Do not reconnect on every tool call — each reconnect generates a new auth event and counts toward the rate limit.
- **Initialize domains sequentially, not in parallel.** Connecting to `/im`, `/food`, `/dineout`, and `/scenes` simultaneously multiplies your auth event count by 4. Connect to one domain, wait for success, then connect to the next.
- **Never create a new initialize handshake per tool invocation.** One persistent session handles all tool calls. Reinitializing per call is the most common cause of rate limit breaches in production.
- **Stop all connection attempts immediately on receiving a block or rejection.** Continued auth attempts after a block extend the incident window. If blocked, raise a request to [builders@swiggy.in](mailto:builders@swiggy.in).

## What triggers the rate limit

- Reconnecting on every request or every tool call
- Parallel multi-domain initialization (`/im` + `/food` + `/dineout` + `/scenes` simultaneously)
- Missing or broken backoff logic on connection errors
- Long-running automated jobs that reinitialize sessions periodically

## Voice & ambient guidance

Voice agents and TV surfaces have different shapes than text chat:

- **Lower QPS, higher burstiness** - a user says "order food" and your agent makes 4-6 tool calls in 3 seconds.
- **Peak-hour amplification** - Indian mealtime traffic (12:00-14:00, 19:00-22:00 IST) amplifies through voice surfaces; your daily budget may be fine while your hourly peak isn't.
- **Stick to `your_go_to_items` for reorders** - one call replaces 3-5 search calls for a returning user.

Enterprise voice/ambient partners get a rate-limit profile shaped to their surface, not the developer-tier defaults.
