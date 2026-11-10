// Cloudflare Worker proxy for ChatGPT subscription check.
// Deploy: Cloudflare Dashboard -> Workers & Pages -> Create -> paste this file
// -> Deploy -> copy the *.workers.dev URL -> paste it as PROXY_URL in index.html
// (or set it in the Proxy URL box on the page - it is saved in your browser only).
//
// Security: the accessToken is used for ONE upstream call and never logged
// or stored. Only the sanitised subscription fields are returned.

const UPSTREAM = 'https://chatgpt.com/backend-api/accounts/check/v4-2023-04-27';

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...CORS },
  });
}

export default {
  async fetch(request) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: CORS });
    }
    if (request.method !== 'POST') {
      return json({ error: 'POST {accessToken} only' }, 405);
    }
    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: 'Invalid JSON body' }, 400);
    }
    const token = body && body.accessToken;
    if (!token || typeof token !== 'string' || !token.startsWith('eyJ')) {
      return json({ error: 'Missing or invalid accessToken' }, 400);
    }

    let upstream;
    try {
      upstream = await fetch(UPSTREAM, {
        headers: {
          Authorization: 'Bearer ' + token,
          Accept: '*/*',
          'Accept-Language': 'en-US,en;q=0.9',
          Referer: 'https://chatgpt.com/',
          Origin: 'https://chatgpt.com',
          'User-Agent':
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
        },
      });
    } catch (e) {
      return json({ error: 'Upstream request failed: ' + String(e && e.message || e) }, 502);
    }

    if (upstream.status === 401) {
      return json({ error: 'Session expired (401). Get a fresh Session JSON.' }, 401);
    }
    if (!upstream.ok) {
      return json({ error: 'ChatGPT returned ' + upstream.status }, upstream.status);
    }

    const data = await upstream.json();
    // Sanitise: return only what the checker UI needs, nothing else.
    const accounts = {};
    for (const [id, info] of Object.entries(data.accounts || {})) {
      accounts[id] = {
        account: {
          plan_type: info.account?.plan_type,
          structure: info.account?.structure,
        },
        entitlement: {
          subscription_plan: info.entitlement?.subscription_plan,
          has_active_subscription: info.entitlement?.has_active_subscription,
          expires_at: info.entitlement?.expires_at,
          renews_at: info.entitlement?.renews_at,
          billing_period: info.entitlement?.billing_period,
        },
      };
    }
    return json({ accounts });
  },
};
