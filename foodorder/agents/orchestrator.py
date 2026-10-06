"""Orchestrator: the conversation the user actually has.

Surface-agnostic: the CLI (interfaces/cli.py) and Telegram bot (interfaces/telegram_bot.py)
pass in their own `confirm`, `say` and `choices` callbacks.

It never touches the cart or places an order itself - those go through CartAgent /
CheckoutAgent (see delegate_cart / delegate_checkout in prompts.py), each a separate,
narrowly-tooled Claude call. The orchestrator keeps only Discover/Track/Support-stage
Swiggy tools, memory tools, and the show_options UI tool - see agents/prompts.py for why
that split is the main defense against hallucination.
"""

import json
import os
import time
from collections.abc import Awaitable, Callable

import anthropic

from foodorder.agents.cart_agent import CartAgent
from foodorder.agents.checkout_agent import CheckoutAgent
from foodorder.agents.gate import DECLINED, confirm_gated
from foodorder.agents.harness import LEAD_TEXT_ARG, AgentHarness
from foodorder.agents.router import Intent, classify
from foodorder.agents.prompts import (
    DELEGATE_CART_TOOL,
    DELEGATE_CART_TOOL_NAME,
    DELEGATE_CHECKOUT_TOOL,
    DELEGATE_CHECKOUT_TOOL_NAME,
    ORCHESTRATOR_SYSTEM_PROMPT,
)
from foodorder.flows.base import Flow, FlowContext
from foodorder.flows.grocery import GroceryFlow
from foodorder.flows.info import order_history, spending, track_order
from foodorder.flows.ingredients import plan
from foodorder.flows.order import OrderFlow, find_usual
from foodorder.providers import GROCERY_PROVIDERS, ProviderHub, split_tool_name
from foodorder.tools.memory import MEMORY_TOOL_NAMES, MEMORY_TOOLS, profile_context, run_memory_tool
from foodorder.tools.ui import SHOW_OPTIONS_TOOL, SHOW_OPTIONS_TOOL_NAME

# Conversations are short-lived; preferences/history persist in the DB. Bounding the
# transcript keeps latency and cost flat (menus alone can be 150 items).
IDLE_RESET_S = int(os.environ.get("FOODORDER_IDLE_RESET_S", "3600"))
MAX_MESSAGES = int(os.environ.get("FOODORDER_MAX_MESSAGES", "80"))

# Swiggy MCP "Discover" + "Track" + "Support" stage tools (https://mcp.swiggy.com/builders/docs/reference/food/).
# create_address/delete_address are here too (they're account edits, not ordering) - they stay
# gated via hub.is_gated(), same as any risky tool.
ORCHESTRATOR_MCP_TOOL_NAMES = {
    "create_address", "delete_address", "get_addresses", "get_restaurant_menu", "search_menu", "search_restaurants",
    "get_food_delivery_status", "get_food_order_details", "get_food_orders", "track_food_order",
    "report_error",
}

ConfirmFn = Callable[[str, str], Awaitable[bool]]  # (title, details) -> approved?
SayFn = Callable[[str], Awaitable[None]]
ChoicesFn = Callable[[str, list[str]], Awaitable[None]]  # (question, options) -> render as buttons


class FoodAgent:
    def __init__(
        self,
        hub: ProviderHub,
        user_id: int,
        confirm: ConfirmFn,
        say: SayFn,
        trace: SayFn | None = None,
        surface_hint: str | None = None,
        choices: ChoicesFn | None = None,
        grocery_platforms: tuple[str, ...] = GROCERY_PROVIDERS,
    ):
        self.hub = hub
        self.user_id = user_id
        self.confirm = confirm
        self.say = say
        self.trace = trace
        self.surface_hint = surface_hint
        self.choices = choices
        self.grocery_platforms = grocery_platforms  # Zepto is owner-only (see providers.OWNER_ONLY_PROVIDERS)
        self.client = anthropic.AsyncAnthropic()
        self.tools = (
            self.hub.claude_tools(ORCHESTRATOR_MCP_TOOL_NAMES)
            + MEMORY_TOOLS
            + [DELEGATE_CART_TOOL, DELEGATE_CHECKOUT_TOOL]
            + ([SHOW_OPTIONS_TOOL] if choices else [])
        )
        self.messages: list[dict] = []
        self.last_active = time.monotonic()
        self.flow: Flow | None = None  # an open guided flow waiting for the user's pick
        self._notes: list[str] = []  # what flows did, told to the agent on its next turn

    def reset(self) -> None:
        """Start a fresh conversation. Long-term memory lives in the DB, and carts live server-side."""
        self.messages = []
        self.flow = None
        self._notes = []

    @property
    def needs_reset(self) -> bool:
        idle = time.monotonic() - self.last_active > IDLE_RESET_S
        return bool(self.messages) and (idle or len(self.messages) > MAX_MESSAGES)

    async def turn(self, user_text: str) -> None:
        if self.needs_reset:
            self.reset()
        self.last_active = time.monotonic()

        # 1. An open guided flow gets the first look: a button tap or a typed answer ("2", "Home").
        if self.flow and not self.flow.done and await self.flow.on_input(user_text):
            self._collect_flow()
            return

        # 2. Common requests run as fast, code-driven flows (they need buttons, so not on button-less surfaces).
        if self.choices:
            intent = await classify(self.client, user_text, self._router_context())
            if self.trace:
                await self.trace(f"[router] {intent.model_dump(exclude_none=True)}")
            if await self._run_intent(intent):
                return

        # 3. Everything else: the agent. If a flow was open, tell the agent where the user was.
        if self.flow and not self.flow.done:
            self._notes.append(f"The user left a guided order midway ({self.flow.progress()}).")
        self.flow = None
        await self._agent_turn(user_text)

    # ---------- routing ----------

    def _flow_context(self) -> FlowContext:
        return FlowContext(self.hub, self.user_id, self.client, self.say, self.choices, self.confirm, self.trace)

    def _router_context(self) -> str | None:
        if self.flow and not self.flow.done:
            return f"The user is midway through a guided order ({self.flow.progress()})."
        return None

    async def _run_intent(self, intent: Intent) -> bool:
        """Run the flow for this intent. False = no flow fits; the agent should handle it."""
        ctx = self._flow_context()
        if intent.intent == "order_food" and intent.dish:
            self.flow = OrderFlow(ctx, intent.dish, intent.people, intent.veg_only, intent.max_price)
        elif intent.intent == "my_usual":
            usual = find_usual(self.user_id)
            if not usual:
                return False  # no rebuildable order yet: the agent can suggest from preferences instead
            self.flow = OrderFlow(ctx, usual=usual)
        elif intent.intent == "grocery" and intent.grocery_items:
            self.flow = GroceryFlow(ctx, intent.grocery_items, self.grocery_platforms)
        elif intent.intent == "cook_dish" and intent.dish:
            shopping = await plan(self.client, intent.dish, intent.people)
            if not shopping or not shopping.main:
                return False
            listed = ", ".join(f"{i.name} {i.quantity or ''}".strip() for i in shopping.main)
            pantry = ", ".join(i.name for i in shopping.pantry)
            title = (f"🍲 {intent.dish.title()} for {intent.people or 2}: you'll need {listed}."
                     + (f"\nAssuming you have the basics: {pantry}." if pantry else ""))
            self.flow = GroceryFlow(ctx, shopping.main, ("instamart",), title=title, pantry=shopping.pantry)
        elif intent.intent == "track_order":
            await self.say(await track_order(ctx))
            return True
        elif intent.intent == "spending":
            await self.say(spending(ctx, intent.days))
            return True
        elif intent.intent == "order_history":
            await self.say(order_history(ctx))
            return True
        else:
            return False
        await self.flow.start()
        self._collect_flow()
        return True

    def _collect_flow(self) -> None:
        if self.flow and self.flow.done:
            if self.flow.summary:
                self._notes.append(self.flow.summary)
            self.flow = None

    # ---------- agent ----------

    async def _agent_turn(self, user_text: str) -> None:
        if self._notes:
            user_text = f"[Since your last reply, via guided flows: {' '.join(self._notes)}]\n{user_text}"
            self._notes = []
        if not self.messages:
            hint = f"<surface>{self.surface_hint}</surface>\n" if self.surface_hint else ""
            user_text = f"{hint}{profile_context(self.user_id, sorted(self.hub.sessions))}\n\n{user_text}"
        last = self.messages[-1] if self.messages else None
        if last and last["role"] == "user" and isinstance(last["content"], list):
            # The previous turn ended on show_options: its tool_result is waiting in a user message,
            # so the pick joins that same message (keeps roles alternating).
            last["content"].append({"type": "text", "text": user_text})
        else:
            self.messages.append({"role": "user", "content": user_text})

        harness = AgentHarness(
            self.client,
            ORCHESTRATOR_SYSTEM_PROMPT,
            self.tools,
            self._dispatch,
            on_text=self.say,
            turn_ending_tools=frozenset({SHOW_OPTIONS_TOOL_NAME}) if self.choices else frozenset(),
            speak_interim=False,
            on_interim=self.trace,
        )
        await harness.run(self.messages)

    # ---------- tools ----------

    async def _dispatch(self, name: str, args: dict) -> tuple[str, bool]:
        if self.trace:
            await self.trace(f"→ {name}({json.dumps(args, ensure_ascii=False)[:160]})")

        if name == SHOW_OPTIONS_TOOL_NAME and self.choices:
            options = [str(o)[:64] for o in args.get("options", [])][:8]
            question = args.get("question") or "Choose one:"
            lead = (args.get(LEAD_TEXT_ARG) or "").strip()
            # One message per step: anything the model said alongside the buttons goes above them.
            await self.choices(f"{lead}\n\n{question}" if lead else question, options)
            return "Shown to the user as buttons. Their pick follows below.", False

        if name in MEMORY_TOOL_NAMES:
            return run_memory_tool(self.user_id, name, args)

        if name == DELEGATE_CART_TOOL_NAME:
            return await self._delegate_cart(args)
        if name == DELEGATE_CHECKOUT_TOOL_NAME:
            return await self._delegate_checkout(args)

        parsed = split_tool_name(name)
        if not parsed:
            return f"Unknown tool {name}", True
        provider, tool = parsed

        if not await confirm_gated(self.hub, self.confirm, provider, tool, args):
            return DECLINED, True

        text, _structured, is_error = await self.hub.call(provider, tool, args)
        return text, is_error

    async def _delegate_cart(self, args: dict) -> tuple[str, bool]:
        agent = CartAgent(self.client, self.hub, self.confirm, trace=self.trace)
        task = f"restaurantId={args.get('restaurantId')} addressId={args.get('addressId')}\n{args.get('task', '')}"
        return await agent.run(task), False

    async def _delegate_checkout(self, args: dict) -> tuple[str, bool]:
        agent = CheckoutAgent(self.client, self.hub, self.user_id, self.confirm, trace=self.trace)
        task = f"addressId={args.get('addressId')} paymentMethod={args.get('paymentMethod') or '(default)'}\n{args.get('task', '')}"
        restaurant = {"id": args.get("restaurantId"), "name": args.get("restaurantName")}
        return await agent.run(task, address_line=args.get("addressLine"), restaurant=restaurant), False
