#!/usr/bin/env python3
"""ChatGPT subscription checker proxy — stdlib only, no pip install needed.

Run on a VPS (e.g. Contabo):
    python3 server.py          # listens on 0.0.0.0:8787
    # or: PORT=8787 python3 server.py

POST /check  {"accessToken": "eyJ..."}
  -> calls https://chatgpt.com/backend-api/accounts/check/v4-2023-04-27
  -> returns only the sanitised subscription fields.

GET /checker  serves the checker page (index.html from the repo root),
  so the page itself comes from this VPS. The browser then calls the
  relative path /check on the same origin — it never sees the upstream
  endpoint, which lives only in this file on the server.

Star Checking hub:
  GET /star     hub page (repo root index.html)
  GET /checker  ChatGPT checker (chatgpt/index.html)
  GET /grok     Grok checker (grok/index.html)
  POST /grok-check  Grok subscription + weekly usage, using the token
    from ~/.grok/auth.json (written by `grok login --device-auth`).
    No token is ever pasted by the user or sent to the browser.

The accessToken is used for one upstream call and never logged or stored.
Use behind Caddy/Nginx with HTTPS in production; do not expose plain HTTP
to the public internet.
"""
import json
import os
import urllib.request
import urllib.error
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = Path(__file__).resolve().parent.parent
HUB_PAGE = BASE / "index.html"
CHATGPT_PAGE = BASE / "chatgpt" / "index.html"
GROK_PAGE = BASE / "grok" / "index.html"
GROK_AUTH = Path.home() / ".grok" / "auth.json"

GROK_SUBS = "https://grok.com/rest/subscriptions"
GROK_BILLING = "https://cli-chat-proxy.grok.com/v1/billing?format=credits"

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


def get_grok_token():
    """Read the xAI OAuth Bearer token from ~/.grok/auth.json.

    The file is a map scope -> credential object; prefer the
    auth.x.ai OIDC entry (auth_mode web_login). Returns the `key`
    string, or None when no login exists yet.
    """
    try:
        store = json.loads(GROK_AUTH.read_text())
    except Exception:
        return None
    if not isinstance(store, dict):
        return None
    cands = list(store.values())
    for c in cands:
        if isinstance(c, dict) and c.get("auth_mode") == "web_login" and c.get("key"):
            return c["key"]
    for scope, c in store.items():
        if isinstance(c, dict) and "auth.x.ai" in scope and c.get("key"):
            return c["key"]
    for c in cands:
        if isinstance(c, dict) and c.get("key"):
            return c["key"]
    return None


def grok_tier(subs):
    """Pick the active subscription and map it to a tier name.

    `subs` is the parsed /rest/subscriptions payload (shape varies, so
    this scans defensively for a status containing ACTIVE and an
    offer id). Returns (tier, active, offer_id).
    """
    items = []
    if isinstance(subs, dict):
        raw = subs.get("subscriptions") or subs.get("items") or []
        if isinstance(raw, list):
            items = raw
        elif isinstance(subs.get("status"), str):
            items = [subs]
    elif isinstance(subs, list):
        items = subs
    active_item = None
    for it in items:
        if not isinstance(it, dict):
            continue
        status = str(it.get("status") or "")
        if "ACTIVE" in status.upper():
            active_item = it
            break
    if active_item is None and items:
        active_item = items[0] if isinstance(items[0], dict) else None
    if not active_item:
        return "Unknown", False, None
    offer = active_item.get("activeOffer") or {}
    offer_id = str(
        (offer.get("providerOfferId") if isinstance(offer, dict) else None)
        or active_item.get("providerOfferId")
        or active_item.get("offerId")
        or active_item.get("planId")
        or ""
    )
    tier_hint = str(
        active_item.get("tier") or active_item.get("plan") or ""
    )
    hay = (offer_id + " " + tier_hint).lower()
    if "heavy" in hay:
        tier = "SuperGrok Heavy"
    elif "lite" in hay:
        tier = "SuperGrok Lite"
    elif "supergrok" in hay or "pro" in hay or "premium" in hay:
        tier = "SuperGrok"
    elif "premium+" in hay or "xpremium" in hay:
        tier = "X Premium+"
    elif "free" in hay:
        tier = "Free"
    else:
        tier = tier_hint or offer_id or "SuperGrok"
    status = str(active_item.get("status") or "")
    return tier, "ACTIVE" in status.upper(), offer_id or None


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

    def _send_html(self, page):
        try:
            body = page.read_bytes()
        except Exception:
            self._send(404, {"error": "checker page not found on server"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/star", "/star/"):
            self._send_html(HUB_PAGE)
        elif path in ("/checker", "/checker/", "/chatgpt", "/chatgpt/"):
            self._send_html(CHATGPT_PAGE)
        elif path in ("/grok", "/grok/"):
            self._send_html(GROK_PAGE)
        elif path in ("/", "/health"):
            self._send(200, {"ok": True, "service": "star-checking"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/grok-check":
            self._grok_check()
            return
        if self.path != "/check":
            self._send(404, {"error": "POST /check or /grok-check only"})
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

    def _grok_check(self):
        token = get_grok_token()
        if not token:
            self._send(401, {"error": "Grok login မလုပ်ရသေးဘူး — VPS မှာ `grok login --device-auth` လုပ်ပါ။"})
            return
        headers = {
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
            "User-Agent": UA,
        }
        try:
            req = urllib.request.Request(GROK_SUBS, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                subs = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self._send(401, {"error": "Grok session expired — VPS မှာ `grok login --device-auth` ပြန်လုပ်ပါ။"})
            else:
                self._send(e.code, {"error": f"Grok returned {e.code}"})
            return
        except Exception as e:
            self._send(502, {"error": f"Grok request failed: {e}"})
            return
        tier, active, offer_id = grok_tier(subs)
        # Weekly usage — best-effort, never fails the check.
        billing = {}
        billing_keys = []
        try:
            bheaders = dict(headers)
            bheaders["X-XAI-Token-Auth"] = "xai-grok-cli"
            req = urllib.request.Request(GROK_BILLING, headers=bheaders)
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = json.loads(resp.read())
            cfg = raw.get("config") if isinstance(raw, dict) else None
            src = cfg if isinstance(cfg, dict) else (raw if isinstance(raw, dict) else {})
            billing_keys = list(src.keys()) if isinstance(src, dict) else []
            billing = {
                "creditUsagePercent": src.get("creditUsagePercent"),
                "currentPeriod": src.get("currentPeriod"),
                "prepaidBalance": src.get("prepaidBalance"),
            }
        except Exception:
            billing = {}
        result = {
            "tier": tier,
            "active": active,
            "offer": offer_id,
            "billing": billing,
        }
        # Debug aid only: field NAMES (never values) so a missed response
        # shape can be fixed without exposing account data.
        if not active:
            subs_keys = list(subs.keys()) if isinstance(subs, dict) else []
            first_keys = []
            items = []
            if isinstance(subs, dict):
                raw_items = subs.get("subscriptions") or subs.get("items") or []
                if isinstance(raw_items, list):
                    items = raw_items
            elif isinstance(subs, list):
                items = subs
            if items and isinstance(items[0], dict):
                first_keys = list(items[0].keys())
            result["debug"] = {
                "subsKeys": subs_keys,
                "firstItemKeys": first_keys,
                "billingKeys": billing_keys,
            }
        self._send(200, result)

    def log_message(self, *args):
        # Do not log request bodies / tokens.
        pass


if __name__ == "__main__":
    print(f"Star Checking proxy on http://0.0.0.0:{PORT}  (POST /check, /grok-check)")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
