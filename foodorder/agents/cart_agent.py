"""Cart agent: builds/edits the Swiggy cart and applies the best coupon.

Delegated to by the orchestrator for one task at a time; it never talks to the user
directly - its only output is the short summary string `run()` returns, which the
orchestrator relays. None of its tools spend money (Swiggy's cart stage is free to
build/edit), so it needs no human-confirmation gate.
"""

import json
from collections.abc import Awaitable, Callable

import anthropic

from foodorder.agents.harness import AgentHarness
from foodorder.agents.prompts import CART_AGENT_SYSTEM_PROMPT
from foodorder.providers import ProviderHub, split_tool_name
from foodorder.tools.coupons import COUPON_TOOL, COUPON_TOOL_NAME, run_coupon_tool

# Swiggy MCP "Cart" stage tools (https://mcp.swiggy.com/builders/docs/reference/food/) - exactly what this agent may call.
CART_MCP_TOOL_NAMES = {"get_food_cart", "update_food_cart", "flush_food_cart", "fetch_food_coupons", "apply_food_coupon"}
MAX_ITERATIONS = 8

TraceFn = Callable[[str], Awaitable[None]] | None


class CartAgent:
    def __init__(self, client: anthropic.AsyncAnthropic, hub: ProviderHub, trace: TraceFn = None):
        self.client = client
        self.hub = hub
        self.trace = trace

    async def run(self, task: str) -> str:
        tools = self.hub.claude_tools(CART_MCP_TOOL_NAMES) + [COUPON_TOOL]
        harness = AgentHarness(
            self.client, CART_AGENT_SYSTEM_PROMPT, tools, self._dispatch, max_iterations=MAX_ITERATIONS
        )
        result = await harness.run([{"role": "user", "content": task}])
        return result.final_text

    async def _dispatch(self, name: str, args: dict) -> tuple[str, bool]:
        if self.trace:
            await self.trace(f"[cart] → {name}({json.dumps(args, ensure_ascii=False)[:160]})")
        if name == COUPON_TOOL_NAME:
            return await run_coupon_tool(self.hub, name, args)
        parsed = split_tool_name(name)
        if not parsed:
            return f"Unknown tool {name}", True
        provider, tool = parsed
        text, _structured, is_error = await self.hub.call(provider, tool, args)
        return text, is_error
