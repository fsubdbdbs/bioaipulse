"""
auth.py — Google Health API OAuth 2.0 Authorization Flow
BioAI-Pulse Project

Handles:
  - First-time authorization (opens browser, exchanges code for tokens)
  - Token persistence (tokens/google_tokens.json)
  - Automatic token refresh when access token expires

Usage:
  python3 auth.py              # Run first-time auth flow
  from auth import get_headers  # Import in other scripts to get valid headers
"""

import os
import ssl
import json
import time
import base64
import secrets
import webbrowser
import urllib.parse
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CLIENT_ID     = os.getenv("FITBIT_CLIENT_ID")
CLIENT_SECRET = os.getenv("FITBIT_CLIENT_SECRET")
REDIRECT_URI  = os.getenv("FITBIT_REDIRECT_URI", "https://franek-health.duckdns.org:8080/callback")

SSL_CERTFILE  = os.getenv("SSL_CERTFILE", "/etc/letsencrypt/live/franek-health.duckdns.org/fullchain.pem")
SSL_KEYFILE   = os.getenv("SSL_KEYFILE",  "/etc/letsencrypt/live/franek-health.duckdns.org/privkey.pem")

TOKENS_PATH   = Path("tokens/google_tokens.json")

AUTH_URL      = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URL     = "https://oauth2.googleapis.com/token"

SCOPES = [
    "https://www.googleapis.com/auth/fitness.activity.read",
    "https://www.googleapis.com/auth/fitness.heart_rate.read",
    "https://www.googleapis.com/auth/fitness.sleep.read",
    "https://www.googleapis.com/auth/fitness.body.read",
]

# ---------------------------------------------------------------------------
# Token storage
# ---------------------------------------------------------------------------

def save_tokens(token_data: dict) -> None:
    TOKENS_PATH.parent.mkdir(parents=True, exist_ok=True)
    token_data["saved_at"] = time.time()
    with open(TOKENS_PATH, "w") as f:
        json.dump(token_data, f, indent=2)
    print(f"[auth] Tokens saved → {TOKENS_PATH}")


def load_tokens() -> dict | None:
    if not TOKENS_PATH.exists():
        return None
    with open(TOKENS_PATH, "r") as f:
        return json.load(f)


def tokens_expired(token_data: dict, buffer_seconds: int = 300) -> bool:
    saved_at   = token_data.get("saved_at", 0)
    expires_in = token_data.get("expires_in", 3600)
    return time.time() >= (saved_at + expires_in - buffer_seconds)


# ---------------------------------------------------------------------------
# OAuth helpers
# ---------------------------------------------------------------------------

def build_auth_url(state: str) -> str:
    params = {
        "response_type":   "code",
        "client_id":       CLIENT_ID,
        "redirect_uri":    REDIRECT_URI,
        "scope":           " ".join(SCOPES),
        "state":           state,
        "access_type":     "offline",   # required to get refresh_token
        "prompt":          "consent",   # force consent screen to always get refresh_token
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_tokens(code: str) -> dict:
    response = requests.post(
        TOKEN_URL,
        data={
            "code":          code,
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uri":  REDIRECT_URI,
            "grant_type":    "authorization_code",
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def refresh_access_token(refresh_token: str) -> dict:
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        timeout=15,
    )
    response.raise_for_status()
    token_data = response.json()
    # Google doesn't always return a new refresh_token — preserve the old one
    existing = load_tokens()
    if "refresh_token" not in token_data and existing:
        token_data["refresh_token"] = existing["refresh_token"]
    save_tokens(token_data)
    print("[auth] Access token refreshed.")
    return token_data


# ---------------------------------------------------------------------------
# Local HTTPS callback server
# ---------------------------------------------------------------------------

_auth_code:  str | None = None
_auth_state: str | None = None


class _CallbackHandler(BaseHTTPRequestHandler):

    def do_GET(self) -> None:  # noqa: N802
        global _auth_code, _auth_state

        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        error  = params.get("error", [None])[0]
        code   = params.get("code",  [None])[0]
        state  = params.get("state", [None])[0]

        if error:
            body = f"<h2>Authorization failed: {error}</h2>".encode()
            self.send_response(400)
        elif code:
            _auth_code  = code
            _auth_state = state
            body = b"<h2>Authorization successful. You can close this tab.</h2>"
            self.send_response(200)
        else:
            body = b"<h2>Unexpected response.</h2>"
            self.send_response(400)

        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


def _wait_for_callback(host: str = "0.0.0.0", port: int = 8080) -> str:
    server = HTTPServer((host, port), _CallbackHandler)

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=SSL_CERTFILE, keyfile=SSL_KEYFILE)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)

    print(f"[auth] Waiting for callback on https://franek-health.duckdns.org:{port}/callback ...")
    while _auth_code is None:
        server.handle_request()
    server.server_close()
    return _auth_code


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_first_time_auth() -> dict:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise EnvironmentError(
            "FITBIT_CLIENT_ID and FITBIT_CLIENT_SECRET must be set in .env"
        )

    state    = secrets.token_urlsafe(16)
    auth_url = build_auth_url(state)

    print(f"\n[auth] Open this URL in your browser:\n\n{auth_url}\n")

    code = _wait_for_callback()

    if _auth_state != state:
        raise ValueError("State mismatch — possible CSRF. Aborting.")

    print("[auth] Code received. Exchanging for tokens...")
    token_data = exchange_code_for_tokens(code)
    save_tokens(token_data)
    print("[auth] Authorization complete.")
    return token_data


def get_valid_tokens() -> dict:
    token_data = load_tokens()

    if token_data is None:
        raise RuntimeError(
            "No tokens found. Run `python3 auth.py` first to authorize."
        )

    if tokens_expired(token_data):
        print("[auth] Access token expired — refreshing...")
        token_data = refresh_access_token(token_data["refresh_token"])

    return token_data


def get_headers() -> dict:
    tokens = get_valid_tokens()
    return {
        "Authorization": f"Bearer {tokens['access_token']}",
        "Accept":        "application/json",
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    existing = load_tokens()

    if existing and not tokens_expired(existing):
        print("[auth] Valid tokens already exist. Nothing to do.")
        remaining = int((existing["saved_at"] + existing.get("expires_in", 3600) - time.time()) / 60)
        print(f"       Access token expires in ~{remaining} minutes.")
    elif existing and tokens_expired(existing):
        print("[auth] Tokens expired — refreshing...")
        refresh_access_token(existing["refresh_token"])
    else:
        run_first_time_auth()
