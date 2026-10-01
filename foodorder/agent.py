"""Swiggy food-ordering agent: Claude drives the Swiggy Food MCP tools from a terminal chat.

Safety: tools that spend money or change account data never run on the model's
say-so alone. The agent loop intercepts them, shows the live cart/address, and
requires the human to type "yes" in the terminal.
"""

import json
import os
import sys
from contextlib import AsyncExitStack
from typing import Any

import anthropic
import anyio
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from rich.console import Console
from rich.markdown import Markdown
from rich.prompt import Prompt

from foodorder.auth import FileTokenStorage, build_oauth_provider

load_dotenv()

FOOD_URL = os.environ.get("SWIGGY_FOOD_URL", "https://mcp.swiggy.com/food")
MODEL = os.environ.get("FOODORDER_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("FOODORDER_EFFORT", "medium")

# Tools that need a human "yes" typed in the terminal before they run.
GATED_TOOLS = {"place_food_order", "create_address", "delete_address"}

SYSTEM_PROMPT = """You are a food-ordering assistant for Swiggy (India), using the Swiggy Food MCP tools.

How to work:
- Start by calling get_addresses to resolve the delivery address; ask which one if it's ambiguous.
- Only recommend restaurants whose availabilityStatus is "OPEN". Mention rating, distance/ETA and price.
- A cart holds items from one restaurant. Warn the user before an action that would clear an existing cart.
- Call get_food_cart before you propose placing an order, and show items, total and the delivery address.
- Call get_payment_options and tell the user which payment method will be used.
- The Builders Club limit is Rs 1000 per order; if the cart total is over it, ask the user to remove items.
- Placing an order spends real money. The app asks the user to confirm in the terminal before
  place_food_order runs; if the tool result says the user declined, don't retry - ask what to change.
- For UPI: a PENDING_PAYMENT response means the order is NOT placed yet. Share the payment link,
  then use check_payment_status and confirm_order. Only announce success after confirm_order succeeds.
- For cancellations, don't call a tool: tell the user to call Swiggy customer care at 080-67466729.
- Keep replies short and scannable; use Rs amounts as returned by the tools, never invent prices or IDs."""

console = Console()


def mcp_result_to_text(result: Any) -> tuple[str, bool]:
    """Flatten an MCP CallToolResult into text for a Claude tool_result block."""
    is_error = bool(getattr(result, "is_error", False))
    parts = []
    structured = getattr(result, "structured_content", None)
    for block in getattr(result, "content", None) or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    if not parts and structured is not None:
        parts.append(json.dumps(structured, ensure_ascii=False))
    text = "\n".join(parts) or "(empty result)"
    try:
        if json.loads(text).get("success") is False:
            is_error = True
    except (ValueError, AttributeError):
        pass
    return text, is_error


class FoodAgent:
    def __init__(self, session: ClientSession, tools: list[dict]):
        self.session = session
        self.tools = tools
        self.client = anthropic.Anthropic()
        self.messages: list[dict] = []

    async def call_mcp(self, name: str, args: dict) -> tuple[str, bool]:
        result = await self.session.call_tool(name, args)
        return mcp_result_to_text(result)

    async def confirm_gated(self, name: str, args: dict) -> bool:
        """Show the human exactly what will happen, then require an explicit 'yes'."""
        console.rule(f"[bold yellow]Confirmation required: {name}")
        if name == "place_food_order":
            cart_text, _ = await self.call_mcp("get_food_cart", {})
            console.print("[bold]Live cart from Swiggy:[/bold]")
            console.print(_pretty(cart_text))
        console.print("[bold]Tool arguments:[/bold]")
        console.print(json.dumps(args, indent=2, ensure_ascii=False))
        answer = await anyio.to_thread.run_sync(
            lambda: Prompt.ask("[bold yellow]Type 'yes' to proceed[/bold yellow]", default="no")
        )
        return answer.strip().lower() == "yes"

    async def run_tool(self, name: str, args: dict) -> tuple[str, bool]:
        if name in GATED_TOOLS and not await self.confirm_gated(name, args):
            return "The user declined this action in the confirmation prompt. Nothing was done.", True
        console.print(f"[dim]→ {name}({json.dumps(args, ensure_ascii=False)[:160]})[/dim]")
        try:
            return await self.call_mcp(name, args)
        except Exception as e:  # surface transport/tool errors to the model instead of crashing
            return f"Tool call failed: {e}", True

    def create(self):
        return self.client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": EFFORT},
            cache_control={"type": "ephemeral"},
            system=SYSTEM_PROMPT,
            tools=self.tools,
            messages=self.messages,
        )

    async def turn(self, user_text: str) -> None:
        self.messages.append({"role": "user", "content": user_text})
        while True:
            response = await anyio.to_thread.run_sync(self.create)
            # Append the full content (incl. thinking blocks) so history stays append-only.
            self.messages.append({"role": "assistant", "content": response.content})

            for block in response.content:
                if block.type == "text" and block.text.strip():
                    console.print(Markdown(block.text))

            if response.stop_reason == "refusal":
                console.print("[red]The model declined this request.[/red]")
                return
            if response.stop_reason != "tool_use":
                return

            results = []
            for block in response.content:
                if block.type == "tool_use":
                    text, is_error = await self.run_tool(block.name, dict(block.input or {}))
                    results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": text, "is_error": is_error}
                    )
            self.messages.append({"role": "user", "content": results})


def to_claude_tool(tool: Any) -> dict:
    """Convert an MCP tool to a Claude tool definition.

    Claude rejects oneOf/anyOf/allOf at the top level of input_schema. Swiggy uses a
    top-level anyOf of `required` sets (addressId OR latitude+longitude), so we drop it
    and state the constraint in the description instead; the server still enforces it.
    """
    schema = dict(tool.input_schema)
    description = tool.description or ""
    notes = []
    for key in ("anyOf", "oneOf", "allOf"):
        variants = schema.pop(key, None)
        if not variants:
            continue
        options = [" + ".join(v.get("required", [])) or json.dumps(v) for v in variants]
        joiner = " AND " if key == "allOf" else " OR "
        notes.append(f"Required: {joiner.join(options)}.")
    if notes:
        description = f"{description}\n\n{' '.join(notes)}".strip()
    return {"name": tool.name, "description": description, "input_schema": schema}


def _pretty(text: str) -> str:
    try:
        return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except ValueError:
        return text


async def main() -> None:
    storage = FileTokenStorage()
    if "--logout" in sys.argv:
        storage.clear_tokens()
        console.print("Logged out (local Swiggy token removed).")
        return

    auth = build_oauth_provider(FOOD_URL, storage)
    async with AsyncExitStack() as stack:
        http = await stack.enter_async_context(create_mcp_http_client(auth=auth))
        read, write = await stack.enter_async_context(streamable_http_client(FOOD_URL, http_client=http))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()

        listed = await session.list_tools()
        # Stable order keeps the prompt cache warm.
        tools = [to_claude_tool(t) for t in sorted(listed.tools, key=lambda t: t.name)]
        console.print(f"[green]Connected to Swiggy Food — {len(tools)} tools.[/green]")

        if "--list-tools" in sys.argv:
            for t in tools:
                console.print(f"• [bold]{t['name']}[/bold]: {t['description'][:100]}")
            return

        if "--check" in sys.argv:
            result = await session.call_tool("get_addresses", {})
            console.print(_pretty(mcp_result_to_text(result)[0]))
            return

        agent = FoodAgent(session, tools)
        console.print("What would you like to eat? (type 'quit' to exit)\n")
        while True:
            user = await anyio.to_thread.run_sync(lambda: Prompt.ask("[bold cyan]you[/bold cyan]"))
            if user.strip().lower() in {"quit", "exit", "q"}:
                break
            if user.strip():
                await agent.turn(user)


def run() -> None:
    try:
        anyio.run(main)
    except KeyboardInterrupt:
        console.print("\nBye!")


if __name__ == "__main__":
    run()
