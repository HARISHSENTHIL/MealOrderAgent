"""Shared Claude tool-calling loop.

The orchestrator and every delegated worker (CartAgent, CheckoutAgent) run through this
exact same loop - one implementation of the retry/history/stop-reason mechanics instead
of each agent re-growing its own copy of a while-True loop.
"""

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

import anthropic

MODEL = os.environ.get("FOODORDER_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("FOODORDER_EFFORT", "medium")

# (tool_name, args) -> (result text for the model, is_error)
ToolDispatch = Callable[[str, dict], Awaitable[tuple[str, bool]]]
OnText = Callable[[str], Awaitable[None]]

StopReason = Literal["end_turn", "refusal", "max_iterations", "awaiting_user"]

# Argument key the harness adds to a turn-ending tool's input: the text the model wrote in the
# same response, so the surface can show it in the same message instead of a separate bubble.
LEAD_TEXT_ARG = "_lead_text"


@dataclass
class TurnResult:
    final_text: str
    stop_reason: StopReason


class AgentHarness:
    """One Claude tool-calling loop over a persistent `messages` list.

    `dispatch` runs a single tool call and returns (text, is_error) for the tool_result.
    `on_text`, if given, is called with every text block as it streams out - the
    orchestrator wires this to showing the user live replies; a delegated worker leaves
    it unset, since its intermediate reasoning is not user-facing, only its final summary
    (the return value of `run()`) is, as a tool_result handed back to the orchestrator.
    `max_iterations` bounds a delegated worker so a confused agent can't loop forever; the
    orchestrator leaves it unset - a live chat runs as long as the user keeps talking.
    `turn_ending_tools` (e.g. show_options) hand control back to the user: after they run, the
    loop stops instead of asking the model to continue, so it can't narrate the buttons it just
    showed. Text the model wrote in that same response is not sent on its own; it is passed to
    the tool as LEAD_TEXT_ARG so the surface can fold it into the same message.
    `speak_interim=False` keeps text written alongside other tool calls ("Resolve address first.")
    out of the chat: it's the model working, not talking to the user. It goes to `on_interim`
    (a debug trace) instead. Only final replies and turn-ending tools reach the user.
    """

    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        system_prompt: str,
        tools: list[dict],
        dispatch: ToolDispatch,
        on_text: OnText | None = None,
        max_iterations: int | None = None,
        model: str = MODEL,
        effort: str = EFFORT,
        max_tokens: int = 16000,
        turn_ending_tools: frozenset[str] = frozenset(),
        speak_interim: bool = True,
        on_interim: OnText | None = None,
    ):
        self.client = client
        self.system_prompt = system_prompt
        self.tools = tools
        self.dispatch = dispatch
        self.on_text = on_text
        self.max_iterations = max_iterations
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.turn_ending_tools = turn_ending_tools
        self.speak_interim = speak_interim
        self.on_interim = on_interim

    async def _create(self, messages: list[dict]):
        return await self.client.beta.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": self.effort},
            cache_control={"type": "ephemeral"},
            system=self.system_prompt,
            tools=self.tools,
            messages=messages,
        )

    async def run(self, messages: list[dict]) -> TurnResult:
        """Drive `messages` (mutated in place, append-only) until the model stops calling
        tools, refuses, or `max_iterations` is hit."""
        texts: list[str] = []
        iterations = 0
        while True:
            response = await self._create(messages)
            messages.append({"role": "assistant", "content": response.content})
            ends_turn = any(b.type == "tool_use" and b.name in self.turn_ending_tools for b in response.content)
            response_texts = [b.text for b in response.content if b.type == "text" and b.text.strip()]
            texts += response_texts
            calls_tools = any(b.type == "tool_use" for b in response.content)
            interim = calls_tools and not ends_turn and not self.speak_interim
            for text in response_texts:
                if ends_turn:
                    continue  # folded into the turn-ending tool's message below
                if interim:
                    if self.on_interim:
                        await self.on_interim(f"(thinking) {text}")
                elif self.on_text:
                    await self.on_text(text)

            if response.stop_reason == "refusal":
                text = "\n".join(texts) or "Sorry, I can't help with that request."
                if not texts and self.on_text:
                    await self.on_text(text)
                return TurnResult(text, "refusal")
            if response.stop_reason != "tool_use":
                return TurnResult("\n".join(texts), "end_turn")

            iterations += 1
            if self.max_iterations and iterations >= self.max_iterations:
                return TurnResult(await self._force_final(messages), "max_iterations")

            results = []
            for block in response.content:
                if block.type == "tool_use":
                    args = dict(block.input or {})
                    if block.name in self.turn_ending_tools and response_texts:
                        args[LEAD_TEXT_ARG] = "\n\n".join(response_texts)
                    text, is_error = await self.dispatch(block.name, args)
                    results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": text, "is_error": is_error}
                    )
            messages.append({"role": "user", "content": results})
            if ends_turn:
                # The user's reply (e.g. a button tap) is appended to this same user message by the caller.
                return TurnResult("\n".join(texts), "awaiting_user")

    async def _force_final(self, messages: list[dict]) -> str:
        """Hit the step budget: ask once more for a summary instead of another tool call."""
        messages.append(
            {
                "role": "user",
                "content": "You've used your step budget. Reply now with a short summary of what you've "
                "done and what's unresolved; do not call another tool.",
            }
        )
        response = await self._create(messages)
        messages.append({"role": "assistant", "content": response.content})
        final = "\n".join(b.text for b in response.content if b.type == "text" and b.text.strip())
        return final or "Ran out of steps without finishing."
