"""
QuickBooks Online OAuth one-time setup script.

Run this ONCE PER COMPANY (once for GCD, once for MH).
It opens a browser, lets you log into the correct QuickBooks company,
grabs the resulting realmId + refresh_token, and saves them into the
`qbo_tokens` table in Supabase.

Setup before running:
    pip install intuit-oauth requests python-dotenv

.env must contain:
    QBO_CLIENT_ID
    QBO_CLIENT_SECRET
    QBO_REDIRECT_URI              e.g. http://localhost:8000/callback
    QBO_ENVIRONMENT               "production" or "sandbox"
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY

Usage:
    python qbo_oauth_setup.py
    (it will prompt: "Which office are you authorizing? GCD/MH")
"""

import http.server
import os
import socketserver
import threading
import urllib.parse
import webbrowser

import requests
from dotenv import load_dotenv
from intuitlib.client import AuthClient
from intuitlib.enums import Scopes

load_dotenv()

CLIENT_ID = os.environ["QBO_CLIENT_ID"]
CLIENT_SECRET = os.environ["QBO_CLIENT_SECRET"]
REDIRECT_URI = os.environ.get("QBO_REDIRECT_URI", "http://localhost:8000/callback")
ENVIRONMENT = os.environ.get("QBO_ENVIRONMENT", "production")
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

_result = {}


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Catches the redirect Intuit sends back after the user approves access."""

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        _result["code"] = params.get("code", [None])[0]
        _result["realmId"] = params.get("realmId", [None])[0]

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        if _result.get("code"):
            self.wfile.write(
                b"<h2>Authorized. You can close this tab and return to the terminal.</h2>"
            )
        else:
            self.wfile.write(b"<h2>No authorization code received. Check the terminal.</h2>")

        threading.Thread(target=self.server.shutdown).start()

    def log_message(self, format, *args):
        pass  # silence default request logging


def get_authorization_code(auth_client: AuthClient) -> tuple[str, str]:
    parsed_redirect = urllib.parse.urlparse(REDIRECT_URI)
    port = parsed_redirect.port or 8000

    auth_url = auth_client.get_authorization_url([Scopes.ACCOUNTING])

    print("\nOpening browser for QuickBooks login...")
    print("IMPORTANT: make sure the company switcher shows the RIGHT company")
    print("(GCD or MH) before you click Connect / Authorize.\n")
    print(f"If the browser doesn't open automatically, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    # Allow quick re-runs if the previous callback left the port in TIME_WAIT.
    socketserver.TCPServer.allow_reuse_address = True
    host = parsed_redirect.hostname or "localhost"
    server = socketserver.TCPServer((host, port), CallbackHandler)
    server.serve_forever()
    server.server_close()

    if not _result.get("code"):
        raise RuntimeError("No authorization code received. Did you approve access?")

    return _result["code"], _result["realmId"]


def save_to_supabase(office: str, realm_id: str, refresh_token: str) -> None:
    url = f"{SUPABASE_URL}/rest/v1/qbo_tokens"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    from datetime import datetime, timezone

    payload = {
        "office": office,
        "realm_id": realm_id,
        "refresh_token": refresh_token,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=15)
    if resp.status_code not in (200, 201, 204):
        print("\nSupabase save FAILED:", resp.status_code, resp.text)
        print("Save this manually into the qbo_tokens table instead:")
        print(payload)
    else:
        print(f"\nSaved {office} tokens to Supabase (qbo_tokens table).")


def main() -> None:
    office = input("Which office are you authorizing right now? (GCD/MH): ").strip().upper()
    if office not in ("GCD", "MH"):
        raise SystemExit("Must be GCD or MH")

    auth_client = AuthClient(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        environment=ENVIRONMENT,
    )

    code, realm_id = get_authorization_code(auth_client)
    print(f"\nGot authorization code and realmId: {realm_id}")

    auth_client.get_bearer_token(code, realm_id=realm_id)
    refresh_token = auth_client.refresh_token

    print("\n--- SAVE THESE SOMEWHERE SAFE TOO (backup) ---")
    print(f"office:        {office}")
    print(f"realm_id:      {realm_id}")
    print(f"refresh_token: {refresh_token}")
    print("------------------------------------------------\n")

    save_to_supabase(office, realm_id, refresh_token)


if __name__ == "__main__":
    main()