"""Telegram front-end: every Telegram user gets their own account and their own Swiggy login.

Login ("Connect Swiggy"):
- Smooth mode: FOODORDER_PUBLIC_URL (e.g. an ngrok static domain forwarding to this machine) is
  whitelisted by Swiggy -> Swiggy redirects to <public>/callback and the bot finishes automatically.
- Paste mode (default today): Swiggy only allows localhost redirects for us. On a phone that page
  fails to load; the user copies its link and pastes it into the chat. On the bot's own machine the
  local listener catches it automatically.

The bot owner can /pair with the code printed in the terminal to reuse the Mac's logins. Orders always
need an explicit tap on ✅.

Zomato is temporarily hidden everywhere (see providers.ENABLED_PROVIDERS) while we focus on Swiggy.
"""

import asyncio
import html
import logging
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from aiohttp import web
from mcp.client.auth import AuthorizationCodeResult
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Conflict
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from foodorder.agents import FoodAgent
from foodorder.core import db, voice
from foodorder.core.auth import CALLBACK_PORT, REDIRECT_URI, LoginRequired, is_redirect_whitelisted, parse_callback_url
from foodorder.core.importer import import_all
from foodorder.providers import ENABLED_PROVIDERS, PROVIDERS, ProviderHub

log = logging.getLogger("foodorder.telegram")

OWNER_REF = "cli:local"  # the Mac user; a paired Telegram account shares its logins/history
PUBLIC_URL = os.environ.get("FOODORDER_PUBLIC_URL", "").rstrip("/")
DAILY_LIMIT = int(os.environ.get("FOODORDER_DAILY_LIMIT", "40"))  # messages/user/day (owner exempt)
CONFIRM_TIMEOUT_S = 300
LOGIN_TIMEOUT_S = 300
TELEGRAM_LIMIT = 4000
SURFACE_HINT = (
    "You are replying inside Telegram on a phone: keep messages short, use bullet lists, never markdown "
    "tables. Prefer show_options buttons whenever the user has to choose."
)
YES = {"yes", "y", "confirm", "place", "ok", "haan", "ha", "✅"}
NO = {"no", "n", "cancel", "stop", "nahi", "❌"}

HOME_BUTTONS = {
    "🔁 My usual": "Order my usual.",
    "🔥 Best deals": "What are the best food deals near me right now?",
    "📦 Track order": "Track my current order.",
    "🧾 My orders": "Show my recent orders.",
}
HOME_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("🔁 My usual"), KeyboardButton("🔥 Best deals")],
     [KeyboardButton("📦 Track order"), KeyboardButton("🧾 My orders")]],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="What are you craving? (type or send a voice note)",
)


@dataclass
class Session:
    user_id: int
    chat_id: int
    hub: ProviderHub
    agent: FoodAgent | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending: asyncio.Future | None = None  # open order confirmation
    pending_nonce: str | None = None
    options: list[str] = field(default_factory=list)  # last show_options buttons
    options_nonce: str | None = None
    login_task: asyncio.Task | None = None


class TelegramLogin:
    """LoginHandler that sends the Swiggy login link as a button and waits for the code."""

    def __init__(self, bot: "FoodBot", s: Session, provider: str):
        self.bot, self.s, self.provider = bot, s, provider
        self.redirect_uri = bot.redirect_uri
        self.state: str | None = None
        self.future: asyncio.Future = asyncio.get_running_loop().create_future()

    async def redirect(self, authorization_url: str, provider_label: str) -> None:
        self.state = parse_qs(urlparse(authorization_url).query).get("state", [None])[0]
        self.bot.pending_logins[self.state] = self
        button = InlineKeyboardMarkup([[InlineKeyboardButton(f"🔐 Log in to {provider_label}", url=authorization_url)]])
        if self.bot.smooth_login:
            steps = "Tap the button, enter your phone number and OTP, and you'll be brought right back here."
        else:
            steps = (
                "1️⃣ Tap the button and log in with your phone number + OTP.\n"
                "2️⃣ You'll then see a page that <b>fails to load</b> (localhost). That's expected!\n"
                "3️⃣ Copy that page's link (⋮ → <i>Copy link</i>) and <b>paste it here within 2 minutes</b>."
            )
        await self.bot.app.bot.send_message(
            self.s.chat_id, f"<b>Connect {provider_label}</b>\n{steps}", parse_mode=ParseMode.HTML, reply_markup=button
        )

    async def wait(self) -> AuthorizationCodeResult:
        try:
            return await asyncio.wait_for(self.future, timeout=LOGIN_TIMEOUT_S)
        finally:
            self.bot.pending_logins.pop(self.state, None)

    def resolve(self, result: AuthorizationCodeResult) -> bool:
        if self.future.done():
            return False
        self.future.set_result(result)
        return True


class FoodBot:
    def __init__(self, token: str):
        self.pair_code = f"{secrets.randbelow(10**6):06d}"
        self.sessions: dict[int, Session] = {}
        self.pending_logins: dict[str, TelegramLogin] = {}
        self.redirect_uri = REDIRECT_URI
        self.smooth_login = False
        self._nudged: set[tuple[int, str]] = set()
        self._bg: list[asyncio.Task] = []
        self._web: web.AppRunner | None = None
        self.app: Application = (
            ApplicationBuilder()
            .token(token)
            .concurrent_updates(True)  # button taps must be handled while a turn is running
            .post_init(self._startup)
            .post_shutdown(self._shutdown)
            .build()
        )
        add = self.app.add_handler
        add(CommandHandler(["start", "help"], self.cmd_start))
        add(CommandHandler("pair", self.cmd_pair))
        add(CommandHandler("login", self.cmd_login))
        add(CommandHandler("new", self.cmd_new))
        add(CommandHandler("status", self.cmd_status))
        add(CommandHandler("import", self.cmd_import))
        add(CommandHandler("forget_me", self.cmd_forget_me))
        add(CallbackQueryHandler(self.on_button))
        add(MessageHandler(filters.VOICE | filters.AUDIO, self.on_voice))
        add(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        self.app.add_error_handler(self._on_error)

    def run(self) -> None:
        print(f"\nTelegram bot starting. To link YOUR Telegram account to this Mac's logins, send:  /pair {self.pair_code}", flush=True)
        print("(Anyone else who messages the bot gets their own account and connects their own Swiggy.)\n", flush=True)
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)

    # ---------- lifecycle ----------

    async def _startup(self, app: Application) -> None:
        if PUBLIC_URL:
            candidate = f"{PUBLIC_URL}/callback"
            if await is_redirect_whitelisted(candidate):
                self.redirect_uri, self.smooth_login = candidate, True
            else:
                log.warning("%s is not whitelisted by Swiggy yet: using paste-the-link login", candidate)
        log.info("login mode: %s (%s)", "smooth" if self.smooth_login else "paste", self.redirect_uri)

        web_app = web.Application()
        web_app.router.add_get("/callback", self._web_callback)
        web_app.router.add_get("/health", lambda r: web.Response(text="ok"))
        self._web = web.AppRunner(web_app)
        await self._web.setup()
        try:
            await web.TCPSite(self._web, "127.0.0.1", CALLBACK_PORT).start()
        except OSError:
            # The port doubles as a single-instance lock: Telegram allows only one poller per bot.
            raise SystemExit(
                f"Port {CALLBACK_PORT} is busy: the bot (or a `foodorder login`) is already running on this Mac. "
                "Stop it first (Ctrl+C in its terminal)."
            )
        self._bg.append(asyncio.create_task(self._nudge_loop()))
        await app.bot.set_my_commands(
            [("start", "Home"), ("new", "Fresh conversation"), ("login", "Connect Swiggy"),
             ("status", "Logins & history"), ("import", "Refresh order history"), ("forget_me", "Delete my data")]
        )

    async def _shutdown(self, app: Application) -> None:
        for t in self._bg:
            t.cancel()
        for s in self.sessions.values():
            await s.hub.close()
        if self._web:
            await self._web.cleanup()

    async def _on_error(self, update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if isinstance(ctx.error, Conflict):
            log.error("Another copy of this bot is running somewhere (Telegram allows only one). Stop the other one.")
            return
        log.error("unhandled error", exc_info=ctx.error)

    # ---------- identity & sessions ----------

    def _owner_id(self) -> int | None:
        return db.find_user(OWNER_REF)

    def _is_owner(self, user_id: int) -> bool:
        return user_id == self._owner_id()

    def _session_for(self, update: Update) -> Session:
        tg = update.effective_user.id
        user_id = db.get_or_create_user(f"tg:{tg}")  # own account unless paired as owner
        s = self.sessions.get(user_id)
        if s is None:
            s = Session(user_id, update.effective_chat.id, ProviderHub(user_id, interactive=False))
            self.sessions[user_id] = s
        s.chat_id = update.effective_chat.id
        return s

    def _allowed_providers(self, s: Session) -> list[str]:
        return [p for p in db.logged_in_providers(s.user_id) if p in ENABLED_PROVIDERS]

    async def _ensure_agent(self, s: Session) -> bool:
        if s.agent is not None and s.hub.sessions:
            return True
        problems = []
        for name in self._allowed_providers(s):  # sequential, per Swiggy guidance
            if name in s.hub.sessions:
                continue
            try:
                await s.hub.connect(name)
            except LoginRequired:
                problems.append(name)
            except Exception as e:  # noqa: BLE001
                log.warning("connect %s for user %s failed: %s", name, s.user_id, e)
        if s.hub.sessions:
            s.agent = FoodAgent(
                s.hub, s.user_id, self._confirm_fn(s), self._say_fn(s),
                surface_hint=SURFACE_HINT, choices=self._choices_fn(s),
            )
        if problems or not s.hub.sessions:
            names = problems or ["swiggy"]
            labels = ", ".join(PROVIDERS[p].label for p in names)
            buttons = [
                [InlineKeyboardButton(f"🔐 Connect {PROVIDERS[p].label}", callback_data=f"login:{p}")]
                for p in names
            ]
            await self.app.bot.send_message(
                s.chat_id,
                f"Your {labels} login has expired or isn't connected yet.",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
        return bool(s.hub.sessions)

    # ---------- login ----------

    def _start_login(self, s: Session, provider: str) -> None:
        if s.login_task and not s.login_task.done():
            return
        s.login_task = asyncio.create_task(self._run_login(s, provider))

    async def _run_login(self, s: Session, provider: str) -> None:
        label = PROVIDERS[provider].label
        try:
            await s.hub.connect(provider, login=TelegramLogin(self, s, provider))
        except Exception as e:  # noqa: BLE001
            root = e
            while isinstance(root, BaseExceptionGroup) and root.exceptions:
                root = root.exceptions[0]
            msg = "Login timed out." if isinstance(root, (TimeoutError, asyncio.TimeoutError)) else "Login didn't go through."
            log.info("login failed for user %s: %r", s.user_id, root)
            await self.app.bot.send_message(
                s.chat_id, f"{msg} Tap to try again.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🔐 Connect {label}", callback_data=f"login:{provider}")]]),
            )
            return
        s.agent = None  # rebuild with the new toolset
        await self._ensure_agent(s)
        await self.app.bot.send_message(
            s.chat_id, f"{label} connected ✅ What are you craving? Type it, tap a button, or send a voice note.",
            reply_markup=HOME_KEYBOARD,
        )

    def _resolve_login(self, result: AuthorizationCodeResult) -> bool:
        login = self.pending_logins.get(result.state or "")
        return bool(login and login.resolve(result))

    async def _web_callback(self, request: web.Request) -> web.Response:
        result = parse_callback_url(str(request.url))
        ok = bool(result and self._resolve_login(result))
        me = self.app.bot.username
        body = (
            f"<h2>{'✅ Connected!' if ok else '⚠️ This login link has expired.'}</h2>"
            f"<p><a href='https://t.me/{me}'>Return to Telegram</a></p>"
        )
        return web.Response(text=f"<html><body style='font-family:sans-serif;text-align:center'>{body}</body></html>",
                            content_type="text/html")

    # ---------- agent callbacks ----------

    def _say_fn(self, s: Session):
        async def say(text: str) -> None:
            for chunk in _chunks(text):
                await _send(self.app.bot, s.chat_id, chunk)

        return say

    def _choices_fn(self, s: Session):
        async def choices(question: str, options: list[str]) -> None:
            s.options, s.options_nonce = options, secrets.token_hex(3)
            rows = [[InlineKeyboardButton(opt, callback_data=f"pick:{s.options_nonce}:{i}")] for i, opt in enumerate(options)]
            await self.app.bot.send_message(
                s.chat_id, md_to_telegram_html(question), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows)
            )

        return choices

    def _confirm_fn(self, s: Session):
        async def confirm(title: str, details: str) -> bool:
            nonce = secrets.token_hex(4)
            s.pending = asyncio.get_running_loop().create_future()
            s.pending_nonce = nonce
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Place order", callback_data=f"confirm:yes:{nonce}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"confirm:no:{nonce}"),
            ]])
            msg = await self.app.bot.send_message(
                s.chat_id, f"<b>{html.escape(title)}</b>\n<pre>{html.escape(details)}</pre>",
                parse_mode=ParseMode.HTML, reply_markup=keyboard,
            )
            try:
                approved = await asyncio.wait_for(s.pending, timeout=CONFIRM_TIMEOUT_S)
            except asyncio.TimeoutError:
                approved = False
                await _safe_edit(msg, "⌛ Confirmation expired. Nothing was ordered.")
            else:
                await _safe_edit(msg, "✅ Confirmed. Placing it now…" if approved else "❌ Cancelled. Nothing was ordered.")
            finally:
                s.pending, s.pending_nonce = None, None
            return approved

        return confirm

    # ---------- message handling ----------

    async def _handle(self, s: Session, text: str) -> None:
        """Single entry point for typed text, button taps and transcribed voice."""
        if s.pending and not s.pending.done():
            word = text.lower().strip(" .!")
            if word in YES | NO:
                s.pending.set_result(word in YES)
            else:
                await self.app.bot.send_message(s.chat_id, "Please tap ✅ or ❌ on the order above first (or reply yes / no).")
            return
        if (result := parse_callback_url(text)) is not None:
            ok = self._resolve_login(result)
            await self.app.bot.send_message(
                s.chat_id, "Got it, finishing login…" if ok else "That login link has expired. Tap Connect again."
            )
            return
        if not self._is_owner(s.user_id) and db.count_message(s.user_id) > DAILY_LIMIT:
            await self.app.bot.send_message(s.chat_id, f"You've reached today's limit of {DAILY_LIMIT} messages. See you tomorrow! 🍽️")
            return
        if not await self._ensure_agent(s):
            return
        text = HOME_BUTTONS.get(text, text)
        if s.lock.locked():
            await self.app.bot.send_message(s.chat_id, "One moment, still working on your last message…")
        async with s.lock:
            typing = asyncio.create_task(_keep_typing(self.app.bot, s.chat_id))
            try:
                await s.agent.turn(text)
            except Exception:  # noqa: BLE001
                log.exception("turn failed for user %s", s.user_id)
                await self.app.bot.send_message(s.chat_id, "Something went wrong on my side. Please try again.")
            finally:
                typing.cancel()

    async def on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._handle(self._session_for(update), update.message.text.strip())

    async def on_voice(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        s = self._session_for(update)
        if not voice.enabled():
            await update.message.reply_text("Voice notes aren't switched on yet. Please type your order 🙂")
            return
        media = update.message.voice or update.message.audio
        if media.duration and media.duration > voice.MAX_VOICE_SECONDS:
            await update.message.reply_text("That's a long one! Please keep voice notes under 2 minutes.")
            return
        await self.app.bot.send_chat_action(s.chat_id, ChatAction.TYPING)
        try:
            audio = bytes(await (await media.get_file()).download_as_bytearray())
            text = await voice.transcribe(audio)
        except Exception as e:  # noqa: BLE001
            log.warning("transcription failed: %s", e)
            await update.message.reply_text("Sorry, I couldn't understand that voice note. Could you type it?")
            return
        if not text:
            await update.message.reply_text("I didn't catch anything in that voice note.")
            return
        await update.message.reply_text(f"🎤 “{text}”")
        await self._handle(s, text)

    async def on_button(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        s = self._session_for(update)
        kind, _, rest = (query.data or "").partition(":")
        if kind == "confirm":
            answer, _, nonce = rest.partition(":")
            if not s.pending or s.pending.done() or nonce != s.pending_nonce:
                await query.answer("This confirmation is no longer active.")
                return
            s.pending.set_result(answer == "yes")
            await query.answer()
        elif kind == "pick":
            nonce, _, idx = rest.partition(":")
            if nonce != s.options_nonce or not idx.isdigit() or int(idx) >= len(s.options):
                await query.answer("Those options have expired.")
                return
            choice = s.options[int(idx)]
            s.options, s.options_nonce = [], None
            await query.answer()
            await _safe_edit(query.message, f"{query.message.text}\n\n👉 {choice}")
            await self._handle(s, choice)
        elif kind == "login":
            provider = rest if rest in ENABLED_PROVIDERS else "swiggy"
            await query.answer()
            self._start_login(s, provider)
        elif kind == "nudge":
            await query.answer()
            await _safe_edit(query.message, query.message.text)
            if rest == "usual":
                await self._handle(s, "Order my usual.")
            elif rest == "new":
                await self._handle(s, "Suggest something new for me based on what I like.")
            else:
                await self.app.bot.send_message(s.chat_id, "No problem 👍")
        else:
            await query.answer()

    # ---------- commands ----------

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        s = self._session_for(update)
        if "swiggy" not in db.logged_in_providers(s.user_id):
            await update.message.reply_text(
                "👋 Hi! I order food for you on Swiggy. Just tell me what you're craving, "
                "type or voice note, and I'll find it, apply the best coupon, and order it after you tap ✅.\n\n"
                "First, connect your own Swiggy account (phone + OTP, takes 30 seconds):",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔐 Connect Swiggy", callback_data="login:swiggy")]]),
            )
            return
        await update.message.reply_text(
            "What are you craving? Type it, tap a button below, or send a voice note 🎤\n"
            "Try: “veg biryani under 250” or “my usual”.",
            reply_markup=HOME_KEYBOARD,
        )

    async def cmd_login(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        s = self._session_for(update)
        provider = (ctx.args or ["swiggy"])[0].lower()
        if provider not in ENABLED_PROVIDERS:
            provider = "swiggy"
        self._start_login(s, provider)

    async def cmd_pair(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Owner only: link this Telegram account to the Mac's logins and history."""
        code = (ctx.args or [""])[0]
        if not secrets.compare_digest(code, self.pair_code):
            await update.message.reply_text("That code doesn't match. (Pairing is only for the bot's owner.)")
            return
        owner = db.get_or_create_user(OWNER_REF)
        tg_user = db.get_or_create_user(f"tg:{update.effective_user.id}")
        db.link_alias(f"tg:{update.effective_user.id}", owner)
        self.pair_code = f"{secrets.randbelow(10**6):06d}"  # one-time use
        old = self.sessions.pop(tg_user, None)
        if old:
            await old.hub.close()
        await update.message.reply_text("Paired ✅ This chat now uses your Mac's Swiggy login and history.",
                                        reply_markup=HOME_KEYBOARD)

    async def cmd_new(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        s = self._session_for(update)
        if s.agent:
            s.agent.reset()
        await update.message.reply_text("Fresh start 🍽️ What are you in the mood for?", reply_markup=HOME_KEYBOARD)

    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        s = self._session_for(update)
        stored = db.logged_in_providers(s.user_id)
        lines = [f"{PROVIDERS[p].label}: {'connected' if p in s.hub.sessions else 'logged in' if p in stored else 'not connected'}"
                 for p in PROVIDERS if p in ENABLED_PROVIDERS]
        lines.append(f"Stored orders: {len(db.search_orders(s.user_id, limit=10000))}")
        prefs = {k: v for k, v in db.get_preferences(s.user_id).items()}
        lines.append("Preferences: " + (", ".join(f"{k}={v}" for k, v in prefs.items()) if prefs else "none yet"))
        await update.message.reply_text("\n".join(lines))

    async def cmd_import(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        s = self._session_for(update)
        if not await self._ensure_agent(s):
            return
        await update.message.reply_text("Importing your order history…")
        async with s.lock:
            result = await import_all(s.hub, s.user_id)
        await update.message.reply_text("\n".join(
            f"{PROVIDERS[p].label}: " + (r["error"] if "error" in r else f"{r['found']} found, {r['new']} new")
            for p, r in result.items()
        ))

    async def cmd_forget_me(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        s = self._session_for(update)
        if self._is_owner(s.user_id):
            await update.message.reply_text("You're the owner: run `uv run foodorder forget-me` on the Mac instead.")
            return
        if (ctx.args or [""])[0].lower() != "confirm":
            await update.message.reply_text("This deletes your Swiggy login, preferences and order history here. "
                                            "Send /forget_me confirm to proceed.")
            return
        await s.hub.close()
        self.sessions.pop(s.user_id, None)
        db.delete_user_data(s.user_id)
        await update.message.reply_text("Done. Everything I stored for you is deleted. 👋")

    # ---------- lunch/dinner nudges ----------

    async def _nudge_loop(self) -> None:
        while True:
            try:
                await self._send_due_nudges()
            except Exception:  # noqa: BLE001
                log.exception("nudge loop error")
            await asyncio.sleep(30)

    async def _send_due_nudges(self) -> None:
        now = datetime.now(db.DISPLAY_TZ)
        hhmm, today = now.strftime("%H:%M"), now.strftime("%Y-%m-%d")
        for user_id, times in db.users_with_preference("nudge_times"):
            slots = {t.strip().zfill(5) for t in re.split(r"[,\s]+", times) if re.fullmatch(r"\d{1,2}:\d{2}", t.strip())}
            key = (user_id, f"{today} {hhmm}")
            if hhmm not in slots or key in self._nudged:
                continue
            meal_start = now.replace(hour=4 if now.hour < 16 else 16, minute=0, second=0, microsecond=0)
            if db.ordered_since(user_id, meal_start):  # this meal is already sorted
                continue
            self._nudged.add(key)
            fav = db.top_dishes(user_id, 1)
            meal = "Lunch" if now.hour < 16 else "Dinner"
            text = (f"🍽️ {meal} time! Your usual is <b>{html.escape(fav[0]['dish'])}</b> from "
                    f"{html.escape(fav[0]['restaurant'] or 'your favourite place')}. Want it?") if fav else \
                   f"🍽️ {meal} time! Want me to find you something good?"
            buttons = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔁 Order my usual" if fav else "🍛 Find food", callback_data="nudge:usual" if fav else "nudge:new"),
                InlineKeyboardButton("✨ Something new", callback_data="nudge:new"),
                InlineKeyboardButton("🔕 Not today", callback_data="nudge:skip"),
            ]])
            for chat_id in db.telegram_ids(user_id):
                try:
                    await self.app.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=buttons)
                except Exception as e:  # noqa: BLE001
                    log.warning("nudge to %s failed: %s", chat_id, e)


# ---------- formatting helpers ----------

def md_to_telegram_html(text: str) -> str:
    """Claude writes Markdown; Telegram's HTML mode is the forgiving option."""
    out = html.escape(text)
    out = re.sub(r"```(?:\w+)?\n?(.*?)```", r"<pre>\1</pre>", out, flags=re.S)
    out = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", out)
    out = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', out)
    out = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", out, flags=re.M)
    out = re.sub(r"^(\s*)[-*]\s+", r"\1• ", out, flags=re.M)
    return out


def _chunks(text: str) -> list[str]:
    if len(text) <= TELEGRAM_LIMIT:
        return [text]
    parts, current = [], ""
    for para in text.split("\n\n"):
        if len(current) + len(para) + 2 > TELEGRAM_LIMIT and current:
            parts.append(current)
            current = ""
        current = f"{current}\n\n{para}" if current else para
        while len(current) > TELEGRAM_LIMIT:
            parts.append(current[:TELEGRAM_LIMIT])
            current = current[TELEGRAM_LIMIT:]
    if current:
        parts.append(current)
    return parts


async def _send(bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, md_to_telegram_html(text), parse_mode=ParseMode.HTML,
                               disable_web_page_preview=True)
    except BadRequest:  # malformed HTML after conversion: fall back to plain text
        await bot.send_message(chat_id, text, disable_web_page_preview=True)


async def _safe_edit(msg, text: str) -> None:
    try:
        await msg.edit_text(text)
    except BadRequest:
        pass


async def _keep_typing(bot, chat_id: int) -> None:
    while True:
        try:
            await bot.send_chat_action(chat_id, ChatAction.TYPING)
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(4)


def run() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2"):  # their INFO lines include the bot token in URLs
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # The MCP SDK logs a traceback when we deliberately abort OAuth (LoginRequired); we handle it.
    logging.getLogger("mcp.client.auth").setLevel(logging.CRITICAL)
    FoodBot(token).run()
