"""Orchestrator-level tools for durable user memory: preferences, order history, spend.

These never touch a live platform, so they carry no hallucination/money risk and stay
with the orchestrator rather than any delegated worker.
"""

import json
from datetime import datetime, timezone

from foodorder.core import db

MEMORY_TOOLS: list[dict] = [
    {
        "name": "remember_preference",
        "description": (
            "Save a durable fact about the user's food preferences so future sessions use it. "
            "Use when the user states a lasting preference (diet, allergies, spice level, budget, "
            "favourite restaurant, default address label, 'my usual'). Keys are short snake_case, "
            "e.g. diet, allergies, spice_level, monthly_budget_inr, usual_order, default_address."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
            "required": ["key", "value"],
        },
    },
    {
        "name": "forget_preference",
        "description": "Delete a saved preference when the user says it no longer applies.",
        "input_schema": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
    },
    {
        "name": "order_history",
        "description": (
            "Search the user's stored order history across platforms (newest first). "
            "Matches restaurant, cuisine or dish name. Results include reorder_items: exact item ids, "
            "variants and add-ons you can pass to the cart agent to repeat an order."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Dish, restaurant or cuisine. Omit for most recent."},
                "provider": {"type": "string", "enum": ["swiggy", "zomato"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
        },
    },
    {
        "name": "spending_summary",
        "description": "Total food spend and order count over the last N days, split by platform.",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 3650}},
            "required": ["days"],
        },
    },
]

MEMORY_TOOL_NAMES = {t["name"] for t in MEMORY_TOOLS}


def run_memory_tool(user_id: int, name: str, args: dict) -> tuple[str, bool]:
    if name == "remember_preference":
        db.set_preference(user_id, args["key"].strip().lower(), args["value"].strip())
        return f"Saved {args['key']} = {args['value']}", False
    if name == "forget_preference":
        ok = db.delete_preference(user_id, args["key"].strip().lower())
        return ("Deleted." if ok else "No such preference."), False
    if name == "order_history":
        rows = db.search_orders(user_id, args.get("search"), args.get("provider"), args.get("limit", 10))
        return json.dumps(rows or "No matching orders stored yet.", ensure_ascii=False, default=str), False
    if name == "spending_summary":
        return json.dumps(db.spending(user_id, int(args["days"]))), False
    return f"Unknown local tool {name}", True


def profile_context(user_id: int, connected: list[str]) -> str:
    """Per-session user profile, sent once at the start of the conversation (keeps the cached prefix stable)."""
    prefs = db.get_preferences(user_id)
    recent = db.search_orders(user_id, limit=5)
    spend = db.spending(user_id, 30)
    lines = [
        f"Today: {datetime.now(timezone.utc).astimezone().strftime('%A %d %b %Y, %H:%M')}",
        f"Connected platforms: {', '.join(connected) or 'none'}",
        f"Saved preferences: {json.dumps(prefs, ensure_ascii=False) if prefs else 'none yet'}",
        f"Favourite dishes: {json.dumps(db.top_dishes(user_id, 8), ensure_ascii=False) if recent else 'no history yet'}",
        "Recent orders: "
        + (
            "; ".join(f"{o['ordered_at'] or '?'} {o['provider']} {o['restaurant_name']} Rs{o['total']}" for o in recent)
            if recent
            else "none stored yet"
        ),
        f"Spend last 30 days: Rs{spend['total_spent']} across {spend['total_orders']} orders",
    ]
    return "<user_profile>\n" + "\n".join(lines) + "\n</user_profile>"
