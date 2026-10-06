"""Dish -> shopping list (no recipe): the ingredients to buy for N people, split into main
ingredients and pantry basics most Indian kitchens already have."""

import logging

import anthropic
from pydantic import BaseModel, Field

from foodorder.agents.router import ROUTER_MODEL, GroceryItem

log = logging.getLogger("foodorder.ingredients")


class ShoppingList(BaseModel):
    main: list[GroceryItem] = Field(description="Ingredients to buy for this dish, with quantities for the servings")
    pantry: list[GroceryItem] = Field(description="Basics most Indian kitchens already have (salt, oil, common spices)")


PLANNER_PROMPT = """You turn a dish into a grocery shopping list for an Indian home cook. No recipe, no steps.

- Scale quantities to the number of people (a typical home portion), rounded to sizes shops sell
  (e.g. "500 g", "1 kg", "200 ml", "1 bunch", "6 pieces").
- main: what must be bought for this dish (meat/fish/paneer, rice/flour, vegetables, dairy, fresh herbs,
  and specific spices or masalas the dish depends on, e.g. "biryani masala").
- pantry: everyday basics most kitchens already stock (salt, cooking oil, sugar, turmeric, red chilli powder,
  cumin, common whole spices). Keep it short.
- Use the names Indian grocery apps list products under: "curd" (not yogurt), "coriander leaves", "mint leaves",
  "basmati rice", "ginger garlic paste", "paneer", "atta". Put only the product in `name`; the amount goes in
  `quantity`. One entry per product; no duplicates between main and pantry."""


async def plan(client: anthropic.AsyncAnthropic, dish: str, people: int | None) -> ShoppingList | None:
    servings = people or 2
    try:
        response = await client.messages.parse(
            model=ROUTER_MODEL,
            max_tokens=2048,
            system=PLANNER_PROMPT,
            messages=[{"role": "user", "content": f"{dish} for {servings} people"}],
            output_format=ShoppingList,
        )
        return response.parsed_output
    except anthropic.APIError as e:
        log.warning("ingredient planner failed: %s", e)
        return None
