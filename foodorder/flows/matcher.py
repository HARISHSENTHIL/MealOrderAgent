"""Pick the right product per grocery item from real search results.

Search results are noisy (Zepto's "chicken boneless" also returns bone-health tablets and dog
treats; "fresh cream" returns whipping cream). One Haiku call chooses, per item, the best
candidate on each platform, but it can only return candidate *indexes*, which code validates.
Names, sizes and prices shown to the user always come from the platform data, never the model.
"""

import logging

import anthropic
from pydantic import BaseModel, Field

from foodorder.agents.router import ROUTER_MODEL

log = logging.getLogger("foodorder.matcher")


class Candidate(BaseModel):
    """One purchasable product variant from a platform's search."""

    platform: str
    name: str
    size: str
    price: float  # rupees, per pack
    ids: dict  # what the platform's cart tool needs (spinId/skuId or productVariantId/storeProductId)
    eta_min: int | None = None  # delivery estimate in minutes, when the platform gives one


class Pick(BaseModel):
    item: int = Field(description="Index of the requested item")
    instamart: int | None = Field(None, description="Chosen Instamart candidate index, or null if none fits")
    zepto: int | None = Field(None, description="Chosen Zepto candidate index, or null if none fits")
    packs: int = Field(1, description="How many packs to buy to cover the requested quantity (1 if not stated)")


class Picks(BaseModel):
    picks: list[Pick]


MATCH_PROMPT = """You match an Indian grocery shopping list to real products from quick-commerce search results.

For each requested item choose the candidate that is genuinely that product (reject unrelated results such as
supplements, pet food, or a different product that merely shares a word; whipping cream is not fresh cream).
Prefer the plain, everyday version: avoid flavoured, Greek, protein, organic, premium or combo packs unless the
request asks for them. Prefer the smallest pack that covers the requested quantity over a much bigger one. When both platforms are listed, prefer equivalent
products (same brand and size) so their prices compare fairly. Choose `packs` so the total covers the requested
quantity (e.g. 1 kg requested, 500 g packs -> 2). Use null when no candidate fits."""


async def match(
    client: anthropic.AsyncAnthropic,
    requests: list[str],
    candidates: dict[str, list[list[Candidate]]],  # platform -> per-item candidate lists
) -> list[Pick]:
    lines = []
    for i, request in enumerate(requests):
        lines.append(f"Item {i}: {request}")
        for platform, per_item in candidates.items():
            for j, c in enumerate(per_item[i]):
                lines.append(f"  {platform}[{j}]: {c.name} · {c.size} · Rs{c.price:g}")
    try:
        response = await client.messages.parse(
            model=ROUTER_MODEL,
            max_tokens=2048,
            system=MATCH_PROMPT,
            messages=[{"role": "user", "content": "\n".join(lines)}],
            output_format=Picks,
        )
        picks = response.parsed_output.picks if response.parsed_output else []
    except anthropic.APIError as e:
        log.warning("matcher failed: %s", e)
        picks = []

    # Validate every index against the real candidate lists; anything out of range becomes "no match".
    by_item: dict[int, Pick] = {}
    for p in picks:
        if 0 <= p.item < len(requests) and p.item not in by_item:
            for platform in ("instamart", "zepto"):
                idx = getattr(p, platform)
                per_item = candidates.get(platform)
                if idx is not None and (per_item is None or not 0 <= idx < len(per_item[p.item])):
                    setattr(p, platform, None)
            p.packs = max(1, min(p.packs, 10))
            by_item[p.item] = p
    return [by_item.get(i, Pick(item=i)) for i in range(len(requests))]
