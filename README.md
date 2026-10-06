# 🍽️ foodorder

**Your household's food brain.** Say what you want, by text or voice, in English, Hinglish or Tamil.
foodorder finds it, picks the best deal, and orders it after a single ✅ tap.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Claude](https://img.shields.io/badge/AI-Claude%20Opus%205.5%20%2B%20Haiku%204.5-D97757)
![MCP](https://img.shields.io/badge/Integration-Model%20Context%20Protocol-6E56CF)
![Telegram](https://img.shields.io/badge/Interface-Telegram-26A5E4?logo=telegram&logoColor=white)
![Postgres](https://img.shields.io/badge/DB-PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![Status](https://img.shields.io/badge/status-beta-orange)

---

## The problem

Ordering food and groceries in India means juggling **four or more apps**: Swiggy, Instamart, Zepto, Zomato.

- **Too many taps.** Search, filter, menu, size, coupon, checkout: a dozen steps for one dinner, every day.
- **No price transparency.** The same basket costs different amounts on different apps. In our own test, the same
  6 grocery items were **₹208 (23%) cheaper** on one app than another, and no app will tell you its competitor
  is cheaper.
- **No one is on your side.** Food apps want you to order; grocery apps want you to cook. None of them helps you
  decide what's best for *your* wallet and time.
- **They forget you.** Your diet, budget and usual order have to be re-entered again and again.

## The solution

foodorder is a conversational agent that sits **on top of the platforms' official APIs** and works for you:

```
You:  want to make mutton biryani for 2 people
Bot:  🍲 Mutton Biryani for 2: you'll need mutton 500 g, basmati rice, onions, curd, mint,
      coriander, biryani masala, ghee…  (assuming you have salt, oil and basic spices)
      Where should it go?   [Home] [Work] [Office]
You:  [Home]
Bot:  🛒 9/10 items found on Instamart · ₹1,134
      mutton 500 g → Deli Chic Mutton Curry Cut 500 g · ₹643
      curd 200 ml  → Amul Pouch Curd 450 g · ₹30
      mint leaves  → out of stock right now
      …
      [🛒 Order on Instamart] [➕ Add pantry basics] [✋ Not now]
```

## ✨ Features

| You say | You get |
|---|---|
| *"Chicken biryani for 2"* | Open restaurants near you as tap-to-pick buttons (rating · delivery time · price), then dish and quantity. No typing |
| *"My usual"* | Your regular order rebuilt exactly (same items, variants and add-ons) |
| *(any order)* | **The cheapest coupon picked automatically**: every applicable coupon is tried on your cart |
| *"I want to make mutton biryani for 2"* | 🍲 **Cook a dish**: the ingredients (no recipe) in the right quantities as an Instamart basket, with pantry basics added only if you want them |
| *"Milk, eggs and 1 kg onions"* | 🛒 **Groceries compared** across Instamart and Zepto, with a plain-language verdict: savings in ₹ and %, the cheaper option per item, what's missing where, and whether splitting is worth two delivery fees |
| *"I'm vegetarian on Tuesdays"* · *"budget ₹3000 a month"* | Remembered permanently and respected in every suggestion |
| *"Where's my order?"* · *"How much did I spend this month?"* | Instant answers from live data and your history |
| 🎤 A voice note in Tamil, Hindi, English or Hinglish | Understood like typed text |

### 🔒 Safe by design

- **Nothing is ever ordered without your ✅.** The confirmation card shows the exact items, total, payment method and
  address. This is enforced in code, not left to the AI.
- **No hallucinated prices.** Every restaurant, product, price and delivery time on a button comes straight from
  the platform's data. The AI only chooses among real results, and code validates its choice.
- **Your account, your data.** Each person signs in to their own Swiggy account (OAuth, phone + OTP). Logins are
  encrypted at rest, and phone numbers and addresses are never stored. One command deletes everything.
- **Orders are never retried automatically**, so a network blip can't place an order twice.

## 🧠 How it works

```
Telegram / Terminal
      │  text · button taps · voice (speech-to-text)
      ▼
Intent router ── Claude Haiku 4.5, ~1 s, structured output
      ├─ order food / my usual ─► guided flow: address → restaurant → dish → qty → cart + best coupon → pay → ✅
      ├─ cook a dish ──────────► ingredient planner → grocery flow (Instamart)
      ├─ groceries ────────────► search Instamart + Zepto → product matcher → comparison → cart → pay → ✅
      ├─ track · spending · history ─► instant answers
      └─ anything else ────────► conversational agent (Claude Opus 5.5) with cart & checkout sub-agents
                                        │
            Model Context Protocol (official servers): Swiggy Food · Instamart · Zepto
                                        │
                              PostgreSQL: users · encrypted logins · orders · preferences
```

**Why this design?** A fast, cheap classifier routes the most common requests into **deterministic, button-driven
flows**, which are quick (0–2 s per step), predictable, and free of made-up values. The large model is kept for
open-ended conversation, where its flexibility actually matters.

### Tech stack

| Layer | Technology |
|---|---|
| AI | [Anthropic Claude](https://www.anthropic.com/) (Opus 5.5 for conversation, Haiku 4.5 for routing, matching and planning) via the official `anthropic` SDK |
| Commerce integrations | [Model Context Protocol](https://modelcontextprotocol.io/) (`mcp` SDK) with OAuth 2.1 + PKCE: Swiggy Food, Swiggy Instamart, Zepto |
| Interface | Telegram (`python-telegram-bot`), plus a terminal client (`rich`) |
| Voice | ElevenLabs Scribe speech-to-text |
| Data | PostgreSQL via SQLAlchemy 2; Fernet (`cryptography`) encryption for stored logins |
| Runtime | Python 3.12, asyncio, `uv` |

## 🚀 Getting started

**Prerequisites:** Python 3.12, [uv](https://docs.astral.sh/uv/), PostgreSQL (optional; SQLite is the fallback),
an Anthropic API key, and a Telegram bot token from [@BotFather](https://t.me/BotFather).

```bash
git clone <this-repo> && cd foodorder
uv sync
cp .env.example .env              # add ANTHROPIC_API_KEY and TELEGRAM_BOT_TOKEN
uv run foodorder login swiggy     # sign in with phone + OTP in the browser
uv run foodorder telegram         # start the bot
```

In Telegram, send the bot `/pair <code>` (the code is printed in the terminal) to link your chat to your login.
Anyone else who messages the bot gets their own account and connects their own Swiggy.

<details>
<summary><b>Commands</b></summary>

| Terminal | |
|---|---|
| `uv run foodorder` | Chat in the terminal |
| `uv run foodorder telegram` | Run the Telegram bot |
| `uv run foodorder login swiggy` | Swiggy login (also used for Instamart; expires every 5 days) |
| `uv run foodorder login zepto` | Zepto login (owner only) |
| `uv run foodorder status` | Logins, stored orders, preferences |
| `uv run foodorder import` | Pull past orders into the database |
| `uv run foodorder forget-me` | Delete everything stored for you |

| Telegram | |
|---|---|
| `/start` | Home menu: 🔁 My usual · 🔥 Best deals · 📦 Track order · 🧾 My orders |
| `/login` | Connect your own Swiggy account |
| `/pair <code>` | Owner only: link this chat to the host's logins and history |
| `/new` · `/status` · `/import` · `/forget_me` | Fresh chat · logins & history · refresh history · delete my data |

</details>

<details>
<summary><b>Configuration (<code>.env</code>)</b></summary>

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | required | Claude |
| `TELEGRAM_BOT_TOKEN` | required for the bot | Telegram |
| `FOODORDER_DB_URL` | SQLite in `~/.foodorder/` | e.g. `postgresql+psycopg://user@localhost:5432/foodorder` |
| `FOODORDER_SECRET_KEY` | `~/.foodorder/secret.key` | Encrypts stored logins; keep it with the database |
| `ELEVENLABS_API_KEY` | off | Voice notes |
| `FOODORDER_PUBLIC_URL` | off | Public HTTPS address for automatic login return (once whitelisted by Swiggy) |
| `FOODORDER_DAILY_LIMIT` | `40` | Messages per user per day (owner unlimited) |
| `FOODORDER_MODEL` / `FOODORDER_EFFORT` | `claude-opus-5-5` / `medium` | Conversational agent |
| `FOODORDER_ROUTER_MODEL` | `claude-haiku-4-5` | Router, product matcher and ingredient planner |

</details>

<details>
<summary><b>Project layout</b></summary>

```
foodorder/
  agents/       router (intent), orchestrator, cart & checkout sub-agents, shared harness, confirmation gate
  flows/        guided flows: order (incl. "my usual"), grocery, ingredients, product matcher, info
  tools/        memory (preferences, history, spending), coupons, UI buttons
  providers/    platform registry (which tools need confirmation) and MCP connection hub
  core/         OAuth + encrypted token storage, database, order-history import, voice
  interfaces/   Telegram bot, terminal client
```

</details>

## 🧭 Roadmap

Here are our short-to-long term plans:

**Shipped**

- [x] **Conversational food ordering**: Swiggy Food via the official MCP server, with guided button flows and a ✅ gate enforced in code.
- [x] **Intent router**: Claude Haiku classifies each message in ~1 s across English, Hinglish and Tamil, and routes common requests to fast, deterministic flows.
- [x] **Automatic best coupon**: every applicable coupon is tried on the live cart and the lowest total wins.
- [x] **Memory**: preferences, budgets, order history and "my usual".
- [x] **Multi-user Telegram bot**: every user signs in to their own Swiggy account; logins are encrypted, with per-user limits.
- [x] **PostgreSQL storage** with privacy by design: no phone numbers or addresses stored, one-command data deletion.

**In progress**

- [ ] **Groceries** *(beta)*: grocery lists matched to real products on Instamart and Zepto, with a "Which is better?" price verdict. Ordering is in testing.
- [ ] **Cook a dish** *(beta)*: dish → ingredient basket on Instamart, with optional pantry basics.
- [ ] **Voice notes and mealtime reminders** *(beta)*: built, in user testing.
- [ ] **One-tap sign-in for everyone**: automatic login return once Swiggy approves our callback, replacing today's copy-paste step.

**Planned**

- [ ] **Cook vs Order**: *"Butter chicken for 4"* → order it (₹, minutes) vs cook it (ingredients ₹ + time), side by side, with one tap for either.
- [ ] **Kitchen memory**: know what's already in your kitchen from past grocery orders, buy only what's missing, and suggest dishes before ingredients expire.
- [ ] **Weekly meal plan**: plan cook days and order days within your budget, then buy the week's groceries in one tap.
- [ ] **Live order updates**: proactive messages as your order moves (confirmed → picked up → arriving).
- [ ] **Learning from feedback**: a quick 👍/👎 after each meal sharpens future suggestions.
- [ ] **Group orders**: collect everyone's picks in a Telegram or WhatsApp group, find one restaurant that suits all, and split the bill.
- [ ] **Family mode**: elders order by voice in their own language; the family member who pays approves with a tap.
- [ ] **More platforms**: Zomato and Blinkit as soon as they allow third-party apps through official APIs.
- [ ] **Cloud deployment**: an always-on hosted service with production access from the platforms.

## ⚠️ Platform notes

| | |
|---|---|
| Per-order cap | ₹1,000 on Swiggy developer access |
| Login lifetime | Swiggy logins last 5 days; sign in again with `foodorder login swiggy` |
| Order history | Swiggy's API returns only a few recent orders ([#50](https://github.com/Swiggy/swiggy-mcp-server-manifest/issues/50), [#74](https://github.com/Swiggy/swiggy-mcp-server-manifest/issues/74)); orders placed through foodorder are always saved |
| Zepto | Available to the bot owner only, until Zepto confirms its policy for third-party apps |
| Cancellations | Not supported by the platforms' APIs; contact the platform's customer care |

## Disclaimer

foodorder is an independent project. It is **not affiliated with, endorsed by, or sponsored by** Swiggy, Instamart,
Zepto, Zomato or Blinkit. All trademarks belong to their respective owners. Integrations use the platforms'
official MCP servers and each user's own account, and every order requires the user's explicit confirmation.
