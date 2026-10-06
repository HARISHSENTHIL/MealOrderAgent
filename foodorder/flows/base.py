"""Guided flows: code-driven, button-first conversations for the most common requests.

A flow asks one thing at a time with buttons; the user's tap (or a typed answer) comes back
through `on_input`. Facts shown to the user come straight from Swiggy's data, never from a
model, which is what keeps these paths fast and free of hallucinated prices or restaurants.
"""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import anthropic

from foodorder.providers import ProviderHub

SayFn = Callable[[str], Awaitable[None]]
ChoicesFn = Callable[[str, list[str]], Awaitable[None]]
ConfirmFn = Callable[[str, str], Awaitable[bool]]
TraceFn = Callable[[str], Awaitable[None]] | None

MAX_OPTIONS = 6  # buttons per question; more than this is hard to scan on a phone


@dataclass
class FlowContext:
    hub: ProviderHub
    user_id: int
    client: anthropic.AsyncAnthropic
    say: SayFn
    choices: ChoicesFn
    confirm: ConfirmFn
    trace: TraceFn = None


@dataclass
class Flow:
    """Base class: subclasses implement start() and handle(value) for the pending question."""

    ctx: FlowContext
    done: bool = False
    summary: str | None = None  # what happened, handed to the agent as context afterwards
    _options: dict[str, Any] = field(default_factory=dict)  # label -> value for the open question
    _on_pick: Callable[[Any], Awaitable[None]] | None = None

    async def start(self) -> None:
        raise NotImplementedError

    def progress(self) -> str:
        """One line on where the user is, for the router and the agent."""
        return type(self).__name__

    async def ask(self, question: str, options: list[tuple[str, Any]], on_pick: Callable[[Any], Awaitable[None]]) -> None:
        """Show buttons; on_pick(value) runs when the user chooses one."""
        labels: dict[str, Any] = {}
        for label, value in options:
            label = label[:64]
            while label in labels:  # Telegram shows labels verbatim; keep them unique
                label = f"{label[:61]} ·"
            labels[label] = value
        self._options, self._on_pick = labels, on_pick
        await self.ctx.choices(question, list(labels))

    async def on_input(self, text: str) -> bool:
        """Route the user's reply to the open question. False = not an answer (caller re-routes it)."""
        if not self._options or not self._on_pick:
            return False
        value = self._match(text.strip())
        if value is _NO_MATCH:
            return False
        on_pick, self._options, self._on_pick = self._on_pick, {}, None
        await on_pick(value)
        return True

    def _match(self, text: str) -> Any:
        if text in self._options:
            return self._options[text]
        labels = list(self._options)
        if text.isdigit() and 1 <= int(text) <= len(labels):
            return self._options[labels[int(text) - 1]]
        lowered = text.lower()
        hits = [label for label in labels if lowered and lowered in label.lower()]
        return self._options[hits[0]] if len(hits) == 1 else _NO_MATCH

    def finish(self, summary: str | None = None) -> None:
        self.done, self.summary = True, summary
        self._options, self._on_pick = {}, None


_NO_MATCH = object()

STOPWORDS = {"veg", "vegetarian", "non", "nonveg", "non-veg", "a", "an", "the", "for", "with", "and", "some", "food"}


def dish_tokens(dish: str) -> list[str]:
    """'Vegetarian Chicken-Biryani for 2' -> ['chicken', 'biryani'] (veg is handled by a filter)."""
    words = re.findall(r"[a-z]+", dish.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def money(value: Any) -> str:
    try:
        return f"₹{float(value):,.0f}"
    except (TypeError, ValueError):
        return f"₹{value}" if value is not None else "₹?"
