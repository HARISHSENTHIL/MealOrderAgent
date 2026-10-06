"""Intent router: one fast Haiku call that turns a message into an intent + details.

Common requests (order food, my usual, track, spending, history) then run as guided,
code-driven flows with buttons (see foodorder/flows/); everything else goes to the
orchestrator agent. Structured outputs guarantee the reply parses into `Intent`.
"""

import logging
import os
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

log = logging.getLogger("foodorder.router")

ROUTER_MODEL = os.environ.get("FOODORDER_ROUTER_MODEL", "claude-haiku-4-5")

IntentName = Literal[
    "order_food", "my_usual", "track_order", "spending", "order_history", "grocery", "cook_dish", "other"
]


class GroceryItem(BaseModel):
    name: str = Field(description="Product in plain English, e.g. 'toned milk', 'eggs', 'onion', 'atta'")
    quantity: str | None = Field(None, description="Amount if stated, e.g. '1 litre', '12', '1 kg', '2 packs'")


class Intent(BaseModel):
    intent: IntentName
    dish: str | None = Field(None, description="Dish or cuisine to order, in plain English, e.g. 'chicken biryani'")
    people: int | None = Field(None, description="Number of people eating, if stated")
    veg_only: bool | None = Field(None, description="True only if the user asked for vegetarian food")
    max_price: int | None = Field(None, description="Max price per dish in rupees, if stated")
    days: int | None = Field(None, description="For spending/history: period in days (this month = 30, this week = 7)")
    grocery_items: list[GroceryItem] | None = Field(None, description="For grocery: every item the user listed")


ROUTER_PROMPT = """Classify a message sent to an Indian food-ordering assistant (Swiggy). Messages may be in
English, Hinglish, Tanglish or transliterated Indian languages, often with typos.

Intents:
- order_food: wants a ready-made dish delivered from a restaurant. "chicken briyani for 2 peoples", "biryani khana hai",
  "veg pizza under 300", "order paneer butter masala". Extract dish (fix spelling: "briyani" -> "biryani"),
  people, veg_only, max_price.
- my_usual: wants their usual/regular/last order again. "my usual", "same as last time", "repeat my last order".
- track_order: where is the current order / delivery status / ETA.
- spending: how much they spent on food. Set days if a period is mentioned.
- order_history: wants to see their past orders.
- grocery: wants groceries/household items delivered (quick commerce: Instamart, Zepto). "milk, eggs and bread",
  "1kg onions and 2 tomatoes", "doodh aur anda chahiye", "need atta 5kg". List every item in grocery_items with
  its quantity if stated. Translate item names to plain English ("doodh" -> milk, "anda" -> eggs, "thakkali" -> tomato).
- cook_dish: wants to cook/make a dish themselves and needs its ingredients. "want to make mutton biryani for 2
  people", "ingredients for paneer butter masala", "I'll cook sambar tonight for 4", "biryani banana hai". Extract
  dish and people. (Ordering the cooked dish from a restaurant is order_food.)
- other: everything else: hungry with no dish named, deals/offers, preferences ("I'm vegetarian"), reminders,
  cancellations, complaints, "what should I cook" (no dish chosen yet), questions, greetings, follow-up replies
  to an ongoing conversation.

When unsure, choose other."""


async def classify(client: anthropic.AsyncAnthropic, text: str, context: str | None = None) -> Intent:
    content = f"Context: {context}\n\nMessage: {text}" if context else text
    try:
        response = await client.messages.parse(
            model=ROUTER_MODEL,
            max_tokens=512,
            system=ROUTER_PROMPT,
            messages=[{"role": "user", "content": content}],
            output_format=Intent,
        )
        return response.parsed_output or Intent(intent="other")
    except anthropic.APIError as e:  # router must never block a message: fall back to the agent
        log.warning("router failed, falling back to agent: %s", e)
        return Intent(intent="other")
