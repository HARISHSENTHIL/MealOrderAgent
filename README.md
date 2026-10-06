# foodorder

A food-ordering agent for Swiggy that you talk to from Telegram (text, buttons or voice) or the terminal.
Claude (`claude-opus-5-5`) handles the conversation through a small team of agents. The official Swiggy
MCP server (`https://mcp.swiggy.com/food`) handles search, cart and orders. Plain code handles everything
that touches money, so **no order is ever placed without your explicit ✅ tap**.

Zomato support exists in the code but is hidden while we focus on Swiggy (`providers/registry.py → ENABLED_PROVIDERS`).

## Quick start

```bash
uv sync
cp .env.example .env                 # add ANTHROPIC_API_KEY and TELEGRAM_BOT_TOKEN
uv run foodorder login swiggy        # browser login with phone + OTP (lasts 5 days)
uv run foodorder telegram            # start the bot; send it /pair <code> from your Telegram
```

Postgres must be running if `FOODORDER_DB_URL` points to it (see [Database](#database)).

## What we offer

**Your household's food brain.** Food apps only ever want you to order from them; grocery apps only ever want you
to cook. foodorder is on your side: it remembers what you like, finds the best deal, and (soon) tells you honestly
whether to **order or cook**, and from which app.

### Available today

| You say | You get |
|---|---|
| *"Chicken biryani for 2"* | Open restaurants near you as tap-to-pick buttons (rating · delivery time · price), then dish and quantity, all without typing |
| *"My usual"* | Your regular order rebuilt exactly (same items, variants and add-ons) from your history |
| *(any order)* | **The cheapest coupon picked automatically**: every applicable coupon is tried on your cart and the lowest total wins |
| *"I'm vegetarian on Tuesdays"* / *"budget 3000 a month"* | Remembered permanently; every suggestion respects it, and you're told how much budget is left before ordering |
| *"Remind me at lunch and dinner"* | A nudge at mealtime with your usual, unless you've already ordered that meal |
| 🎤 A voice note in Tamil, Hindi, English or Hinglish | Understood and handled like typed text |
| *"Where's my order?"* | Live status of your Swiggy order |

**Safe by design.** Nothing is ordered until you tap ✅ on a card showing the exact items, total, payment method and
address. Each person uses their own Swiggy account, and we never store phone numbers or addresses.

### Coming next

| Feature | What it does |
|---|---|
| 🍳 **Cook vs Order** | *"Butter chicken for 4"* → **Order** ₹1,350 · 35 min vs **Cook** ₹650 of ingredients from the cheapest of Instamart and Zepto · 12 min delivery + 45 min cooking. One tap for either |
| 🧊 **Kitchen memory** | Knows what's in your kitchen from past grocery orders, so "cook" only buys what you're missing, and suggests dishes before ingredients expire |
| 📅 **Weekly meal plan** | Plans cook days and order days within your budget, buys the week's groceries in one tap, and reminds you each evening |
| 🔁 **Live order updates** | Messages you as your order moves: confirmed → picked up 🛵 → arriving |
| 👍 **Learns from feedback** | A quick rating after each meal sharpens future suggestions |

Zepto and Swiggy Instamart both have official MCP servers, and we've tested their live prices. Blinkit has none, so
it isn't included.

## Commands

| Terminal | |
|---|---|
| `uv run foodorder` | Chat in the terminal |
| `uv run foodorder telegram` | Run the Telegram bot (only one copy can run at a time) |
| `uv run foodorder login swiggy` / `logout swiggy` | Swiggy login (Swiggy logins expire every 5 days) |
| `uv run foodorder status` | Logins, stored orders, preferences |
| `uv run foodorder import` | Pull past orders into the database |
| `uv run foodorder tools swiggy` | List Swiggy's MCP tools |
| `uv run foodorder forget-me` | Delete everything stored for you |

| Telegram | |
|---|---|
| `/start` | Home menu: 🔁 My usual · 🔥 Best deals · 📦 Track order · 🧾 My orders |
| `/pair <code>` | **Owner only**: link your Telegram to this Mac's logins and history (single-use code printed by the bot) |
| `/login` | Connect your own Swiggy account |
| `/new` · `/status` · `/import` · `/forget_me` | Fresh chat · logins & history · refresh history · delete my data |

**Every Telegram user gets their own account** and connects their own Swiggy. Nobody shares your login.

Other users log in by **copy-paste** today: after the OTP, their phone shows a localhost page that fails to load,
and they paste that link into the chat. To make it **automatic**, set `FOODORDER_PUBLIC_URL` to an ngrok static
domain (`ngrok http --url=<domain> 8765`). Once Swiggy whitelists `<domain>/callback`, users return to the bot by
themselves. The bot checks the whitelist when it starts.

## How it works

```
Telegram / Terminal (interfaces/)
        │  text, button taps, voice → text
        ▼
Orchestrator agent (agents/orchestrator.py)    talks to the user; search, menus, tracking, memory
   ├── delegate_cart     → CartAgent       builds/edits the cart, picks the cheapest coupon
   └── delegate_checkout → CheckoutAgent   payment + place order, behind the ✅ confirmation in code
        │
AgentHarness (agents/harness.py)   one Claude tool-calling loop shared by all three agents
        │
ProviderHub (providers/hub.py)     one persistent MCP session per user; reconnects; never retries orders
        │
Swiggy Food MCP  ·  Postgres (core/db.py)
```

**Ground rules the code enforces (not just the prompt):**
- Placing an order and adding or deleting an address need a human ✅ that shows the live cart, total, payment method and address.
- `place_food_order` is never retried automatically, because it isn't idempotent.
- Each agent sees only the tools it needs, e.g. the orchestrator can't touch the cart.
- Each step is one chat message: showing buttons ends the turn, and the model's in-progress notes stay out of the chat.
- Every user has their own account, Swiggy login, memory and history. Non-owners are limited to `FOODORDER_DAILY_LIMIT` messages a day.

## Project layout

```
foodorder/
  agents/       orchestrator, cart_agent, checkout_agent, harness (shared loop), prompts
  tools/        memory (preferences, history, spending), coupons (best-coupon finder), ui (show_options buttons)
  providers/    registry (Swiggy/Zomato definitions, which tools need confirmation), hub (MCP connections)
  core/         auth (OAuth + encrypted token storage), db (schema + queries), importer (order history),
                voice (speech-to-text), utils
  interfaces/   cli, telegram_bot
scripts/
  copy_db.py    copy all data between databases (e.g. SQLite → Postgres, Mac → server)
```

## Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | required | Claude |
| `TELEGRAM_BOT_TOKEN` | required for the bot | Telegram |
| `FOODORDER_DB_URL` | SQLite in `~/.foodorder/` | e.g. `postgresql+psycopg://harish@localhost:5432/foodorder` |
| `FOODORDER_SECRET_KEY` | `~/.foodorder/secret.key` | Encrypts stored logins; keep it with the database |
| `ELEVENLABS_API_KEY` | off | Voice notes |
| `FOODORDER_PUBLIC_URL` | off | ngrok/HTTPS address for the automatic login return (only once Swiggy whitelists it) |
| `FOODORDER_DAILY_LIMIT` | `40` | Messages per user per day (owner unlimited) |
| `FOODORDER_MODEL` / `FOODORDER_EFFORT` | `claude-opus-5-5` / `medium` | Model settings |
| `FOODORDER_IDLE_RESET_S` / `FOODORDER_MAX_MESSAGES` | `3600` / `80` | When a conversation starts fresh (memory is kept) |
| `FOODORDER_CALLBACK_PORT` / `FOODORDER_HOME` | `8765` / `~/.foodorder` | Local login port / data folder |

## Database

Postgres via SQLAlchemy (falls back to SQLite if `FOODORDER_DB_URL` is unset). Tables are created automatically.

| Table | Holds |
|---|---|
| `users`, `user_aliases` | Accounts (`cli:local`, `tg:<id>`) and the owner's paired Telegram |
| `oauth_tokens` | Swiggy logins, **encrypted** with Fernet |
| `orders`, `order_items` | Order history, including the exact item ids that "my usual" uses to rebuild a cart |
| `preferences` | Diet, budget, reminder times… |
| `usage` | Daily message counts |

- Only food data is stored. Phone numbers and addresses never are. `forget-me` deletes everything for a user.
- **Move `secret.key` (or `FOODORDER_SECRET_KEY`) together with the database**; without it the stored logins can't be decrypted.
- Copy data between databases with `uv run python scripts/copy_db.py SOURCE_URL TARGET_URL` (the target must be empty).
- Start Postgres on this Mac (Homebrew's `brew services` is currently broken for postgresql@14):

```bash
/opt/homebrew/opt/postgresql@14/bin/pg_ctl -D /opt/homebrew/var/postgresql@14 -l /opt/homebrew/var/log/postgresql@14.log start
```

## Swiggy platform limits (Oct 2026)

| | |
|---|---|
| Per-order cap | ₹1000 (developer access) |
| Login lifetime | 5 days, no refresh; run `foodorder login swiggy` again |
| Order history | At most ~5 recent orders, and empty for some accounts ([#50](https://github.com/Swiggy/swiggy-mcp-server-manifest/issues/50), [#74](https://github.com/Swiggy/swiggy-mcp-server-manifest/issues/74)). Orders placed through the agent are always saved |
| Rate limit | 70 requests/min per user (30 for writes) |
| Public multi-user bot | Needs production approval and a whitelisted HTTPS callback ([#129](https://github.com/Swiggy/swiggy-mcp-server-manifest/issues/129)) |
| Cancellations | Not possible through the API; Swiggy customer care is 080-67466729 |

Swiggy MCP docs: https://mcp.swiggy.com/builders/docs/
