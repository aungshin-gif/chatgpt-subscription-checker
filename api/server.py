#!/usr/bin/env python3
"""ChatGPT subscription checker proxy — stdlib only, no pip install needed.

Run on a VPS (e.g. Contabo):
    python3 server.py          # listens on 0.0.0.0:8787
    # or: PORT=8787 python3 server.py

POST /check  {"accessToken": "eyJ..."}
  -> calls https://chatgpt.com/backend-api/accounts/check/v4-2023-04-27
  -> returns only the sanitised subscription fields.

The accessToken is used for one upstream call and never logged or stored.
Use behind Caddy/Nginx with HTTPS in production; do not expose plain HTTP
to the public internet.
"""
import json
import os
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = "https://chatgpt.com/backend-api/accounts/check/v4-2023-04-27"
PORT = int(os.environ.get("PORT", "8787"))


UPSTREAM_ME = "https://chatgpt.com/backend-api/me"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0 Safari/537.36"
)


def upstream_headers(token):
    return {
        "Authorization": "Bearer " + token,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://chatgpt.com/",
        "Origin": "https://chatgpt.com",
        "User-Agent": UA,
    }


def fetch_profile(token):
    """Best-effort: GET /backend-api/me for name/phone/picture.

    Returns None if it fails — the subscription check must not fail
    just because the profile call did. Phone is often empty for
    accounts that never verified one.
    """
    try:
        req = urllib.request.Request(UPSTREAM_ME, headers=upstream_headers(token))
        with urllib.request.urlopen(req, timeout=10) as resp:
            me = json.loads(resp.read())
    except Exception:
        return None
    if not isinstance(me, dict):
        return None
    return {
        "name": me.get("name"),
        "email": me.get("email"),
        "phone": me.get("phone"),
        "picture": me.get("picture") or me.get("image"),
        "mfa": me.get("mfa"),
    }


def sanitise(data):
    accounts = {}
    for acc_id, info in (data.get("accounts") or {}).items():
        acct = info.get("account") or {}
        ent = info.get("entitlement") or {}
        accounts[acc_id] = {
            "account": {
                "plan_type": acct.get("plan_type"),
                "structure": acct.get("structure"),
                "name": acct.get("name"),
            },
            "entitlement": {
                "subscription_plan": ent.get("subscription_plan"),
                "has_active_subscription": ent.get("has_active_subscription"),
                "expires_at": ent.get("expires_at"),
                "renews_at": ent.get("renews_at"),
                "billing_period": ent.get("billing_period"),
            },
        }
    return {"accounts": accounts}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        if self.path in ("/", "/health"):
            self._send(200, {"ok": True, "service": "chatgpt-subscription-checker"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/check":
            self._send(404, {"error": "POST /check only"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._send(400, {"error": "Invalid JSON body"})
            return
        token = body.get("accessToken")
        if not token or not isinstance(token, str) or not token.startswith("eyJ"):
            self._send(400, {"error": "Missing or invalid accessToken"})
            return
        req = urllib.request.Request(UPSTREAM, headers=upstream_headers(token))
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self._send(401, {"error": "Session expired (401). Get a fresh Session JSON."})
            else:
                self._send(e.code, {"error": f"ChatGPT returned {e.code}"})
            return
        except Exception as e:
            self._send(502, {"error": f"Upstream request failed: {e}"})
            return
        result = sanitise(data)
        result["profile"] = fetch_profile(token)
        self._send(200, result)

    def log_message(self, *args):
        # Do not log request bodies / tokens.
        pass


if __name__ == "__main__":
    print(f"ChatGPT subscription checker proxy on http://0.0.0.0:{PORT}  (POST /check)")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
