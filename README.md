# ChatGPT Subscription Checker

Paste a ChatGPT Session JSON → check Plus / Pro / Free, expiry date and auto-renewal — like duihuan.us/chatgpt-subscription, on your own site.

**Unofficial:** there is no official OpenAI API for this. This uses ChatGPT's own internal endpoint, the same one the web app uses:

```
GET https://chatgpt.com/backend-api/accounts/check/v4-2023-04-27
Authorization: Bearer <accessToken from chatgpt.com/api/auth/session>
```

Response fields used: `account.plan_type`, `entitlement.subscription_plan`, `entitlement.has_active_subscription`, `entitlement.expires_at`, `entitlement.renews_at`, `entitlement.billing_period`.

## Files

| File | What it is |
|---|---|
| `index.html` | The checker page (Burmese UI). Single file, no build step. |
| `worker.js` | Cloudflare Worker proxy — recommended. Free tier is enough. |
| `api/server.py` | Python proxy (stdlib only) for your own VPS. Alternative to the Worker. |
| `.github/workflows/pages.yml` | Deploys `index.html` to GitHub Pages on every push to `main`. |

## Why a proxy is needed

`chatgpt.com` blocks direct `fetch` from other domains with CORS (no `Access-Control-Allow-Origin` header for other origins). So the browser page alone cannot call the endpoint — the call must go through your own server/Worker, which is not bound by CORS.

## Deploy in 2 steps (5 minutes)

### Step 1 — Proxy (Cloudflare Worker, free)

1. Go to [dash.cloudflare.com](https://dash.cloudflare.com) → Workers & Pages → Create → paste `worker.js` → Deploy.
2. Copy the Worker URL, e.g. `https://chatgpt-checker.xxx.workers.dev` — the check endpoint is that URL + `/check`.
3. Open your checker page, paste that full URL into the **Proxy URL** box. It is saved in your browser only.

### Step 2 — Page (GitHub Pages, automatic)

1. Push this repo to GitHub.
2. Settings → Pages → Source: GitHub Actions. The workflow in this repo deploys `index.html` automatically.
3. Open `https://<username>.github.io/chatgpt-subscription-checker/`.

Alternative proxy on your VPS instead of Cloudflare:

```bash
python3 api/server.py   # POST /check on port 8787, put Caddy/Nginx + HTTPS in front
```

## How a customer checks

1. Log in to ChatGPT in their browser.
2. Open `chatgpt.com/api/auth/session`, copy the whole JSON.
3. Paste it on the checker page → Check subscription.
4. Result shows plan, active yes/no, expires at, renews at, auto-renewal, billing period, days left.

## Security — read this

- A Session JSON **is a login credential** (like a password). This site never saves it, never logs it, and clears the input right after the check. The proxy returns only the subscription fields, nothing else.
- Do not paste a Session into chat, screenshots or public issues.
- If a check returns 401, the session expired — get a fresh one.
- OpenAI can change or block this internal endpoint at any time; it is not a stable public API.
