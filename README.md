# Star Checking

Subscription checkers in one place — pick a category, check the plan.

- **ChatGPT** — paste Session JSON, check Plus / Pro / Free, expiry, auto-renewal.
- **Grok** — no paste needed. The VPS holds the login (one-time `grok login`),
  open the page and tap Check: SuperGrok tier + weekly usage %.

Unofficial tools — not affiliated with OpenAI or xAI.

## Pages

| Page | GitHub Pages | VPS |
|---|---|---|
| Hub (Star Checking) | `https://<user>.github.io/chatgpt-subscription-checker/` | `https://redeem.gamepayhub.shop/star` |
| ChatGPT checker | `…/chatgpt-subscription-checker/chatgpt/` | `https://redeem.gamepayhub.shop/checker` |
| Grok checker | `…/chatgpt-subscription-checker/grok/` | `https://redeem.gamepayhub.shop/grok` |

## How it works

No official APIs. Both checkers use the services' own internal endpoints
through a small Python proxy (`api/server.py`, stdlib only, ~15 MB RAM).

- ChatGPT: `GET chatgpt.com/backend-api/accounts/check/v4-2023-04-27`
  with the `accessToken` from `chatgpt.com/api/auth/session`.
  Direct browser fetch is CORS-blocked, so the proxy is required.
- Grok: `GET grok.com/rest/subscriptions` (plan tier) and
  `GET cli-chat-proxy.grok.com/v1/billing?format=credits` (weekly usage %),
  with the xAI OAuth token from `~/.grok/auth.json`.
  The Grok session JSON from `grok.com/api/auth/session` carries identity
  only — no token — so pasting it cannot work; the token must come from login.

## VPS setup

```bash
# 1. Get the code and run the proxy (port 8787)
git clone https://github.com/aungshin-gif/chatgpt-subscription-checker.git
cd chatgpt-subscription-checker
nohup python3 api/server.py > proxy.log 2>&1 &

# 2. One-time Grok login (device flow for SSH — no browser on the server)
curl -fsSL https://x.ai/cli/install.sh | bash
grok --version
grok login --device-auth   # open the printed URL on your phone and approve
```

## Caddy (example)

```caddy
redeem.gamepayhub.shop {
    handle /check {
        reverse_proxy 127.0.0.1:8787
    }
    handle /checker* {
        reverse_proxy 127.0.0.1:8787
    }
    handle /grok* {
        reverse_proxy 127.0.0.1:8787
    }
    handle /star* {
        reverse_proxy 127.0.0.1:8787
    }
    reverse_proxy 127.0.0.1:3000
}
```

Then `caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy`.

Tokens: the Grok token lives only in `~/.grok/auth.json` on the VPS
(0600, owner-only) and is never sent to the browser. ChatGPT Session JSON
is a login credential — the checker clears it after each check; never share it.
