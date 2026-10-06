"""Terminal front-end.

  foodorder                      chat (connects every platform you're logged in to)
  foodorder login swiggy         browser login (phone + OTP)
  foodorder logout swiggy
  foodorder status               logged-in platforms + stored order count
  foodorder import               pull past orders into the local database
  foodorder tools [provider]     list a platform's tools
  foodorder telegram             run the Telegram bot (TELEGRAM_BOT_TOKEN in .env)
  foodorder forget-me            delete everything stored for you

Zomato is temporarily hidden while we focus on Swiggy (see providers.ENABLED_PROVIDERS).
"""

import json
import sys

import anyio
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

load_dotenv()

from foodorder.agents.orchestrator import FoodAgent  # noqa: E402
from foodorder.core import db  # noqa: E402  (reads env set by load_dotenv)
from foodorder.core.auth import DBTokenStorage, migrate_legacy_files  # noqa: E402
from foodorder.core.importer import import_all  # noqa: E402
from foodorder.providers import ENABLED_PROVIDERS, LOGIN_PROVIDERS, PROVIDERS, ProviderHub  # noqa: E402

console = Console()
CLI_USER = "cli:local"


async def connect_logged_in(hub: ProviderHub, user_id: int) -> None:
    for name in db.logged_in_providers(user_id):  # sequential, per Swiggy guidance
        if name not in ENABLED_PROVIDERS:
            continue
        try:
            await hub.connect(name)
            console.print(f"[green]Connected to {PROVIDERS[name].label} — {len(hub.tools[name])} tools.[/green]")
        except Exception as e:
            console.print(f"[red]Could not connect to {PROVIDERS[name].label}: {e}. Try `foodorder login {name}`.[/red]")


async def cmd_chat(user_id: int) -> None:
    async with ProviderHub(user_id) as hub:
        await connect_logged_in(hub, user_id)
        if not hub.sessions:
            console.print("Not logged in anywhere. Run: [bold]uv run foodorder login swiggy[/bold]")
            return

        async def confirm(title: str, details: str) -> bool:
            console.print(Panel(details, title=f"[bold yellow]{title}", border_style="yellow"))
            answer = await anyio.to_thread.run_sync(
                lambda: Prompt.ask("[bold yellow]Type 'yes' to proceed[/bold yellow]", default="no")
            )
            return answer.strip().lower() == "yes"

        async def say(text: str) -> None:
            console.print(Markdown(text))

        async def trace(text: str) -> None:
            console.print(f"[dim]{text}[/dim]")

        last_options: list[str] = []

        async def choices(question: str, options: list[str]) -> None:
            last_options[:] = options
            console.print(f"[bold]{question}[/bold]")
            for i, opt in enumerate(options, 1):
                console.print(f"  [cyan]{i}[/cyan]. {opt}")

        agent = FoodAgent(hub, user_id, confirm, say, trace, choices=choices)
        console.print("What would you like to eat? (type 'quit' to exit)\n")
        while True:
            user = (await anyio.to_thread.run_sync(lambda: Prompt.ask("[bold cyan]you[/bold cyan]"))).strip()
            if user.lower() in {"quit", "exit", "q"}:
                return
            if user.isdigit() and 1 <= int(user) <= len(last_options):
                user = last_options[int(user) - 1]  # picked a numbered option
            last_options.clear()
            if user:
                await agent.turn(user)


async def cmd_login(user_id: int, name: str) -> None:
    async with ProviderHub(user_id) as hub:
        await hub.connect(name)
        console.print(f"[green]Logged in to {PROVIDERS[name].label}. {len(hub.tools[name])} tools available.[/green]")


async def cmd_tools(user_id: int, name: str) -> None:
    async with ProviderHub(user_id) as hub:
        await hub.connect(name)
        for t in hub.tools[name]:
            props = list((t.input_schema or {}).get("properties", {}))
            console.print(f"• [bold]{t.name}[/bold]({', '.join(props)}): {(t.description or '')[:110]}")


async def cmd_import(user_id: int) -> None:
    async with ProviderHub(user_id) as hub:
        await connect_logged_in(hub, user_id)
        result = await import_all(hub, user_id)
        console.print_json(json.dumps(result))
        console.print(f"Stored orders now: {len(db.search_orders(user_id, limit=10000))}")


def main() -> None:
    args = sys.argv[1:]
    cmd = args[0] if args else "chat"
    user_id = db.get_or_create_user(CLI_USER)
    migrate_legacy_files(user_id)

    def provider_arg() -> str:
        if len(args) < 2 or args[1] not in LOGIN_PROVIDERS:
            console.print(f"Usage: foodorder {cmd} {'|'.join(sorted(LOGIN_PROVIDERS))}")
            sys.exit(2)
        return args[1]

    try:
        if cmd == "chat":
            anyio.run(cmd_chat, user_id)
        elif cmd == "login":
            anyio.run(cmd_login, user_id, provider_arg())
        elif cmd == "logout":
            DBTokenStorage(user_id, provider_arg()).clear_tokens()
            console.print("Logged out.")
        elif cmd == "status":
            for name, p in PROVIDERS.items():
                if name not in ENABLED_PROVIDERS:
                    continue
                state = "logged in" if name in db.logged_in_providers(user_id) else "not logged in"
                console.print(f"{p.label}: {state}")
            console.print(f"Stored orders: {len(db.search_orders(user_id, limit=10000))}")
            console.print(f"Preferences: {db.get_preferences(user_id) or 'none'}")
        elif cmd == "import":
            anyio.run(cmd_import, user_id)
        elif cmd == "tools":
            anyio.run(cmd_tools, user_id, provider_arg())
        elif cmd == "telegram":
            from foodorder.interfaces.telegram_bot import run as run_telegram

            run_telegram()
        elif cmd == "forget-me":
            if Prompt.ask("Delete ALL your stored orders, preferences and logins? Type 'yes'", default="no") == "yes":
                db.delete_user_data(user_id)
                console.print("Deleted.")
        else:
            console.print(__doc__)
    except KeyboardInterrupt:
        console.print("\nBye!")
