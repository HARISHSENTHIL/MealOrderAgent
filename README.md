# 🍽️ foodorder

**Your household's food brain.** Say what you want, by text or voice, in English, Hinglish or Tamil.
foodorder finds it, picks the best deal, and orders it after a single ✅ tap.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Claude](https://img.shields.io/badge/AI-Anthropic%20Claude-D97757)
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

foodorder understands what you want, then follows a guided, button-first flow to get it done. It connects only
to the platforms' **official** integrations, signs in with **your own account**, and never places an order without
your confirmation.

Built with **Anthropic Claude** for understanding natural language, the **Model Context Protocol** for official
commerce integrations, **Telegram** as the chat interface and **PostgreSQL** for secure storage.

## 🧭 Roadmap

Here are our short-to-long term plans:

**Shipped**

- [x] **Conversational food ordering**: Swiggy Food via the official MCP server, with guided button flows and a ✅ gate enforced in code.
- [x] **Instant understanding**: messages in English, Hinglish and Tamil are understood in about a second, and common requests run as fast, guided flows.
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
| Login lifetime | Swiggy sign-ins last 5 days, then you sign in again |
| Order history | Swiggy's API returns only a few recent orders ([#50](https://github.com/Swiggy/swiggy-mcp-server-manifest/issues/50), [#74](https://github.com/Swiggy/swiggy-mcp-server-manifest/issues/74)); orders placed through foodorder are always saved |
| Zepto | Available to the bot owner only, until Zepto confirms its policy for third-party apps |
| Cancellations | Not supported by the platforms' APIs; contact the platform's customer care |

## Disclaimer

foodorder is an independent project. It is **not affiliated with, endorsed by, or sponsored by** Swiggy, Instamart,
Zepto, Zomato or Blinkit. All trademarks belong to their respective owners. Integrations use the platforms'
official MCP servers and each user's own account, and every order requires the user's explicit confirmation.
