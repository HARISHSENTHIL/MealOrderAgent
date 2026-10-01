"""Swiggy OAuth 2.1 + PKCE: file-backed token storage and a localhost callback server.

The mcp SDK's OAuthClientProvider does discovery, dynamic client registration,
PKCE and the token exchange. We only supply storage and the browser round-trip.
"""

import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import anyio
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

STATE_DIR = Path(os.environ.get("FOODORDER_HOME", Path.home() / ".foodorder"))
CALLBACK_PORT = int(os.environ.get("FOODORDER_CALLBACK_PORT", "8765"))
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/callback"


class FileTokenStorage:
    """Persists tokens + registered client info under ~/.foodorder (mode 600)."""

    def __init__(self, directory: Path = STATE_DIR):
        self.dir = directory
        self.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.tokens_path = self.dir / "tokens.json"
        self.client_path = self.dir / "client.json"

    def _write(self, path: Path, data: str) -> None:
        path.write_text(data)
        path.chmod(0o600)

    async def get_tokens(self) -> OAuthToken | None:
        if self.tokens_path.exists():
            return OAuthToken.model_validate_json(self.tokens_path.read_text())
        return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._write(self.tokens_path, tokens.model_dump_json())

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        if self.client_path.exists():
            return OAuthClientInformationFull.model_validate_json(self.client_path.read_text())
        return None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._write(self.client_path, client_info.model_dump_json())

    def clear_tokens(self) -> None:
        self.tokens_path.unlink(missing_ok=True)


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
                    outer.result = AuthorizationCodeResult(
                        code=qs["code"][0], state=qs.get("state", [None])[0]
                    )
                    body = "Swiggy login complete. You can close this tab and return to the terminal."
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
                raise TimeoutError("Timed out waiting for Swiggy login (5 min).")
            if self.error or not self.result:
                raise RuntimeError(f"Swiggy login failed: {self.error}")
            return self.result
        finally:
            self.httpd.shutdown()
            self.httpd.server_close()


def build_oauth_provider(server_url: str, storage: FileTokenStorage) -> OAuthClientProvider:
    server: dict[str, _CallbackServer] = {}

    async def redirect_handler(authorization_url: str) -> None:
        server["s"] = _CallbackServer()
        print("\nOpening your browser to log in to Swiggy (phone + OTP).")
        print(f"If it doesn't open, visit:\n  {authorization_url}\n")
        webbrowser.open(authorization_url)

    async def callback_handler() -> AuthorizationCodeResult:
        return await anyio.to_thread.run_sync(server["s"].wait)

    return OAuthClientProvider(
        server_url=server_url,
        client_metadata=OAuthClientMetadata(
            client_name="foodorder-cli",
            redirect_uris=[REDIRECT_URI],
            grant_types=["authorization_code"],
            response_types=["code"],
            token_endpoint_auth_method="none",
            scope="mcp:tools",
        ),
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )
