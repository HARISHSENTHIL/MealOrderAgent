# foodorder

Terminal agent that orders food on Swiggy. Claude (`claude-opus-5-5`) drives the official
Swiggy Builders Club Food MCP server (`https://mcp.swiggy.com/food`).

## Setup

```bash
uv sync
cp .env.example .env   # add ANTHROPIC_API_KEY
```

## Run

```bash
uv run foodorder --check        # log in to Swiggy (browser, phone + OTP) and list saved addresses
uv run foodorder --list-tools   # show the Swiggy Food tools
uv run foodorder                # chat: "get me a chicken biryani under 300"
uv run foodorder --logout       # forget the local Swiggy token
```

The Swiggy token (valid for 5 days) and the OAuth client registration are stored in `~/.foodorder/` with mode 600.

## Safety

- `place_food_order`, `create_address` and `delete_address` are gated **in code**. Before any of them runs, the
  app fetches the live cart and you must type `yes` in the terminal.
- Swiggy's Builders Club caps each order at Rs 1000. You can pay with Cash on Delivery, or with UPI (a payment link, then
  `check_payment_status` → `confirm_order`).
- To cancel an order, call Swiggy customer care at 080-67466729. The API can't cancel orders.

Docs snapshot: `docs/` (from https://mcp.swiggy.com/builders/llms.txt).
