"""OAuth 2.1 + PKCE for Swiggy/Zomato MCP: encrypted per-user token storage and the browser round-trip.

The mcp SDK's OAuthClientProvider does discovery, dynamic client registration,
PKCE and the token exchange. We supply storage and the redirect/callback handling.
"""

import os
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Protocol
from urllib.parse import parse_qs, urlparse

import anyio
import httpx2
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from foodorder.core import db

CALLBACK_PORT = int(os.environ.get("FOODORDER_CALLBACK_PORT", "8765"))
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/callback"
SWIGGY_REDIRECT_CHECK = "https://mcp.swiggy.com/auth/check-redirect-uri"


class LoginRequired(Exception):
    """Raised instead of opening a browser when running non-interactively (e.g. the Telegram bot)."""

    def __init__(self, provider_label: str):
        super().__init__(f"{provider_label} login required")
        self.provider_label = provider_label


class DBTokenStorage:
    """mcp TokenStorage backed by the encrypted oauth_tokens table, one row per (user, provider)."""

    def __init__(self, user_id: int, provider: str):
        self.user_id = user_id
        self.provider = provider

    async def get_tokens(self) -> OAuthToken | None:
        raw = db.load_token_field(self.user_id, self.provider, "tokens_enc")
        return OAuthToken.model_validate_json(raw) if raw else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        db.save_token_field(self.user_id, self.provider, "tokens_enc", tokens.model_dump_json())

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        raw = db.load_token_field(self.user_id, self.provider, "client_info_enc")
        return OAuthClientInformationFull.model_validate_json(raw) if raw else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        db.save_token_field(self.user_id, self.provider, "client_info_enc", client_info.model_dump_json())

    def clear_tokens(self) -> None:
        db.save_token_field(self.user_id, self.provider, "tokens_enc", None)


def migrate_legacy_files(user_id: int) -> None:
    """Move the v0 plaintext ~/.foodorder/{tokens,client}.json (Swiggy) into the encrypted DB."""
    for name, field in (("tokens.json", "tokens_enc"), ("client.json", "client_info_enc")):
        path = db.STATE_DIR / name
        if path.exists():
            if not db.load_token_field(user_id, "swiggy", field):
                db.save_token_field(user_id, "swiggy", field, path.read_text())
            path.unlink()


class _CallbackServer:
    """One-shot HTTP server that captures ?code=&state= from the OAuth redirect."""

    def __init__(self) -> None:
        self.result: AuthorizationCodeResult | None = None
        self.error: str | None = None
        self.done = threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                url = urlparse(self.path)
                if url.path != "/callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                qs = parse_qs(url.query)
                if "code" in qs:
                    outer.result = _code_result(qs)
                    body = "Login complete. You can close this tab and return to the terminal."
                else:
                    outer.error = qs.get("error_description", qs.get("error", ["unknown error"]))[0]
                    body = f"Login failed: {outer.error}"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(body.encode())
                outer.done.set()

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", CALLBACK_PORT), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def wait(self, timeout: float = 300) -> AuthorizationCodeResult:
        try:
            if not self.done.wait(timeout):
                raise TimeoutError("Timed out waiting for login (5 min).")
            if self.error or not self.result:
                raise RuntimeError(f"Login failed: {self.error}")
            return self.result
        finally:
            self.httpd.shutdown()
            self.httpd.server_close()


class LoginHandler(Protocol):
    """How a login reaches the user and how the authorization code comes back."""

    redirect_uri: str

    async def redirect(self, authorization_url: str, provider_label: str) -> None: ...

    async def wait(self) -> AuthorizationCodeResult: ...


class BrowserLogin:
    """Terminal login: open the system browser, catch the redirect on localhost."""

    redirect_uri = REDIRECT_URI

    def __init__(self) -> None:
        self._server: _CallbackServer | None = None

    async def redirect(self, authorization_url: str, provider_label: str) -> None:
        self._server = _CallbackServer()
        print(f"\nOpening your browser to log in to {provider_label} (phone + OTP).")
        print(f"If it doesn't open, visit:\n  {authorization_url}\n")
        webbrowser.open(authorization_url)

    async def wait(self) -> AuthorizationCodeResult:
        return await anyio.to_thread.run_sync(self._server.wait)


def parse_callback_url(text: str) -> AuthorizationCodeResult | None:
    """Extract code/state from a pasted redirect URL (the 'copy the link' login on a phone)."""
    match = re.search(r"\S*[?&]code=\S+", text)
    if not match:
        return None
    qs = parse_qs(urlparse(match.group(0)).query)
    if "code" not in qs:
        return None
    return _code_result(qs)


def _code_result(qs: dict[str, list[str]]) -> AuthorizationCodeResult:
    """Build the SDK's code result. `iss` (RFC 9207) must be passed through: servers that
    advertise it (e.g. Zepto) are rejected by the SDK's mix-up check if it's dropped."""
    return AuthorizationCodeResult(
        code=qs["code"][0], state=qs.get("state", [None])[0], iss=qs.get("iss", [None])[0]
    )


async def is_redirect_whitelisted(redirect_uri: str) -> bool:
    """Swiggy only redirects to allow-listed URIs (see Swiggy/swiggy-mcp-server-manifest#129)."""
    async with httpx2.AsyncClient(timeout=15) as client:
        try:
            r = await client.get(SWIGGY_REDIRECT_CHECK, params={"redirect_uri": redirect_uri})
            return bool(r.json().get("whitelisted"))
        except Exception:  # noqa: BLE001 - treat unknown as not whitelisted
            return False


def build_oauth_provider(
    server_url: str, storage: DBTokenStorage, label: str, login: LoginHandler | None
) -> OAuthClientProvider:
    """login=None means non-interactive: an expired/missing login raises LoginRequired."""

    async def redirect_handler(authorization_url: str) -> None:
        if login is None:
            raise LoginRequired(label)
        await login.redirect(authorization_url, label)

    async def callback_handler() -> AuthorizationCodeResult:
        return await login.wait()

    return OAuthClientProvider(
        server_url=server_url,
        client_metadata=OAuthClientMetadata(
            client_name="foodorder",
            redirect_uris=[login.redirect_uri if login else REDIRECT_URI],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="none",
            scope="mcp:tools",
        ),
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )
