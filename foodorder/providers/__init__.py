"""Connections to the food-platform MCP servers (Swiggy, Zomato) for one user.

Public surface: `registry.py` (which servers exist, which tools are risky) and
`hub.py` (the live MCP connection + call machinery) are kept separate; this file
re-exports both so callers can do `from foodorder.providers import ProviderHub`.
"""

from foodorder.providers.hub import (
    CALL_TIMEOUT_S,
    SEP,
    ProviderHub,
    parse_result,
    split_tool_name,
    to_claude_tool,
)
from foodorder.providers.registry import ENABLED_PROVIDERS, PROVIDERS, RISKY_NAME, Provider

__all__ = [
    "CALL_TIMEOUT_S",
    "ENABLED_PROVIDERS",
    "PROVIDERS",
    "Provider",
    "ProviderHub",
    "RISKY_NAME",
    "SEP",
    "parse_result",
    "split_tool_name",
    "to_claude_tool",
]
