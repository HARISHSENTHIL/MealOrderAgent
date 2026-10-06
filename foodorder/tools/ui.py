"""Orchestrator-level UI tool: show the user tappable choices instead of free text."""

SHOW_OPTIONS_TOOL = {
    "name": "show_options",
    "description": (
        "Show the user tappable choices (restaurants, dishes, variants, addresses, payment methods, yes/no). "
        "Put everything you want to say in `question`; the buttons are the whole message. The user's tap comes back as their next message, verbatim."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "Short prompt shown above the choices."},
            "options": {
                "type": "array",
                "items": {"type": "string", "maxLength": 64},
                "minItems": 2,
                "maxItems": 8,
            },
        },
        "required": ["question", "options"],
    },
}
SHOW_OPTIONS_TOOL_NAME = SHOW_OPTIONS_TOOL["name"]
