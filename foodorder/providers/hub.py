"""Connections to the food-platform MCP servers for one user.

Per Swiggy's rate-limit guidance: one persistent session per user per server,
servers initialised sequentially, never a reconnect per tool call.
"""

import asyncio
import json
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from foodorder.core.auth import BrowserLogin, DBTokenStorage, LoginHandler, LoginRequired, build_oauth_provider
from foodorder.providers.registry import PROVIDERS, Provider, RISKY_NAME

SEP = "__"  # Claude tool name = "<provider>__<tool>"
CALL_TIMEOUT_S = 90  # a hung upstream call must not hang the chat


def parse_result(result: Any) -> tuple[str, Any, bool]:
    """MCP CallToolResult -> (text for the model, structured payload or None, is_error)."""
    is_error = bool(getattr(result, "is_error", False))
    texts = [b.text for b in (getattr(result, "content", None) or []) if getattr(b, "type", None) == "text"]
    structured = getattr(result, "structured_content", None)
    text = "\n".join(texts) or (json.dumps(structured, ensure_ascii=False) if structured is not None else "")
    if structured is None and texts:
        try:
            structured = json.loads(texts[0])
        except ValueError:
            pass
    if isinstance(structured, dict) and structured.get("success") is False:
        is_error = True
    return text or "(empty result)", structured, is_error


def to_claude_tool(provider: str, tool: Any) -> dict:
    """MCP tool -> Claude tool definition.

    Claude rejects oneOf/anyOf/allOf at the top level of input_schema. Swiggy uses a
    top-level anyOf of `required` sets (addressId OR latitude+longitude), so we drop it
    and state the constraint in the description; the server still enforces it.
    """
    schema = dict(tool.input_schema or {"type": "object", "properties": {}})
    description = f"[{PROVIDERS[provider].label}] {tool.description or ''}".strip()
    for key in ("anyOf", "oneOf", "allOf"):
        variants = schema.pop(key, None)
        if variants:
            options = [" + ".join(v.get("required", [])) or json.dumps(v) for v in variants]
            description += f"\n\nRequired: {(' AND ' if key == 'allOf' else ' OR ').join(options)}."
    return {"name": f"{provider}{SEP}{tool.name}", "description": description, "input_schema": schema}


class _Connection:
    """One MCP session owned by a dedicated background task.

    The MCP transport runs its own task group; if the connection drops, only this task
    dies (not the caller's), and the hub can reconnect.
    """

    def __init__(self, user_id: int, provider: Provider, login: LoginHandler | None):
        self.user_id = user_id
        self.provider = provider
        self.login = login
        self.session: ClientSession | None = None
        self.tools: list[Any] = []
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name=f"mcp-{self.provider.name}-{self.user_id}")
        ready = asyncio.create_task(self._ready.wait())
        await asyncio.wait({self._task, ready}, return_when=asyncio.FIRST_COMPLETED)
        ready.cancel()
        if self._task.done():  # failed before becoming ready: surface the root cause
            raise _root_cause(self._task.exception())

    async def _run(self) -> None:
        auth = build_oauth_provider(
            self.provider.url, DBTokenStorage(self.user_id, self.provider.token_key), self.provider.label, self.login
        )
        async with create_mcp_http_client(auth=auth) as http:
            async with streamable_http_client(self.provider.url, http_client=http) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=CALL_TIMEOUT_S) as session:
                    await session.initialize()
                    self.tools = sorted((await session.list_tools()).tools, key=lambda t: t.name)
                    self.session = session
                    self._ready.set()
                    await self._stop.wait()

    @property
    def alive(self) -> bool:
        return self.session is not None and self._task is not None and not self._task.done()

    async def close(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except BaseException:  # noqa: BLE001 - shutdown must never raise
                self._task.cancel()


def _root_cause(exc: BaseException | None) -> BaseException:
    """Unwrap anyio ExceptionGroups so callers can catch LoginRequired etc."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc or RuntimeError("connection failed")


class ProviderHub:
    """One live MCP session per connected provider for a single user, with reconnect."""

    def __init__(self, user_id: int, interactive: bool = True):
        """interactive=True: log in via the system browser when needed (terminal).
        interactive=False: raise LoginRequired instead (bots); use connect(login=...) to run a login."""
        self.user_id = user_id
        self.interactive = interactive
        self._conns: dict[str, _Connection] = {}

    async def __aenter__(self) -> "ProviderHub":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        for conn in list(self._conns.values()):
            await conn.close()
        self._conns.clear()

    @property
    def sessions(self) -> dict[str, ClientSession]:
        return {n: c.session for n, c in self._conns.items() if c.alive}

    @property
    def tools(self) -> dict[str, list[Any]]:
        return {n: c.tools for n, c in self._conns.items() if c.alive}

    async def connect(self, name: str, login: LoginHandler | None = None) -> None:
        """Connect, logging in if needed. Call sequentially, one provider at a time.
        Raises LoginRequired when no login handler is available and the stored login is missing/expired."""
        if name in self._conns:
            await self._conns.pop(name).close()
        if login is None and self.interactive:
            login = BrowserLogin()
        conn = _Connection(self.user_id, PROVIDERS[name], login)
        await conn.start()
        self._conns[name] = conn

    def claude_tools(self, tool_names: "set[str] | None" = None) -> list[dict]:
        """Claude tool defs for connected providers, optionally restricted to an exact set of
        MCP tool names (e.g. an agent's narrow stage-scoped toolset: {'get_food_cart', ...})."""
        return [
            to_claude_tool(p, t)
            for p in sorted(self.tools)
            for t in self.tools[p]
            if tool_names is None or t.name in tool_names
        ]

    def is_gated(self, provider: str, tool: str) -> bool:
        return tool in PROVIDERS[provider].gated or bool(RISKY_NAME.search(tool))

    async def call(self, provider: str, tool: str, args: dict) -> tuple[str, Any, bool]:
        conn = self._conns.get(provider)
        if conn is None:
            return f"{PROVIDERS[provider].label} is not connected. Ask the user to log in to it.", None, True
        for attempt in range(2):
            if not conn.alive:
                try:
                    await self.connect(provider)  # transparent reconnect after a dropped connection
                    conn = self._conns[provider]
                except LoginRequired:
                    return f"{PROVIDERS[provider].label} login has expired. Ask the user to log in again.", None, True
                except Exception as e:
                    return f"{PROVIDERS[provider].label} is unreachable right now ({e}). Try again shortly.", None, True
            try:
                return parse_result(await conn.session.call_tool(tool, args))
            except Exception as e:
                cause = _root_cause(e)
                if isinstance(cause, LoginRequired):
                    return f"{PROVIDERS[provider].label} login has expired. Ask the user to log in again.", None, True
                # Placing an order is not idempotent (Swiggy docs): never blind-retry it, the first
                # attempt may have gone through. Read-only/cart calls are safe to retry once.
                retryable = not self.is_gated(provider, tool) and tool not in PROVIDERS[provider].order_tools
                if attempt == 0 and retryable and not conn.alive:
                    continue  # connection died mid-call: reconnect once and retry
                if not retryable:
                    return (
                        f"Connection problem during {tool} ({cause}). The order MAY have been placed. "
                        "Check the order list before trying again; do not retry blindly."
                    ), None, True
                return f"Tool call failed: {cause}", None, True
        return "Tool call failed after reconnect.", None, True


def split_tool_name(name: str) -> tuple[str, str] | None:
    if SEP in name:
        provider, tool = name.split(SEP, 1)
        if provider in PROVIDERS:
            return provider, tool
    return None
