# DEPLOY.md — host MiniSuite for free + Cloudflare subdomain

This guide walks through three free hosting options. **Fly.io is the recommended path**
because it gives you an always-on machine, persistent SQLite storage, and clean
custom-domain support. Render is the simplest if you don't mind cold starts, and
Cloudflare Tunnel is great if you already have a machine that's always on.

---

## Option A — Fly.io (recommended)

Fly's free allowance covers a tiny always-on VM with a 1 GB persistent volume — perfect
for this app. The setup is ~10 minutes.

### 1. Install `flyctl` and sign up

```powershell
# Windows PowerShell
iwr https://fly.io/install.ps1 -useb | iex
fly auth signup        # or `fly auth login` if you already have an account
```

You'll need to add a credit card to verify the account, but the free allowance covers
this workload.

### 2. Launch the app from this folder

```bash
cd ridgeline-netsuite
fly launch --no-deploy --copy-config
```

When prompted:
- App name: `ridgeline-minisuite` (or anything globally unique — adjust `fly.toml` to match)
- Region: pick the one closest to you (e.g. `den` for Denver, `iad` for Virginia, `lhr` for London)
- Postgres / Redis / Tigris: **No** to all
- Deploy now: **No** (we need the volume first)

This generates a `.dockerignore` and updates `fly.toml` if needed.

### 3. Create the persistent volume

```bash
fly volumes create minisuite_data --size 1 --region <your-region>
```

The volume name must match `[[mounts]].source` in `fly.toml` (already set to
`minisuite_data`).

### 4. Set your real token as a secret

```bash
fly secrets set MINISUITE_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
fly secrets list
```

(Or pick your own value. Multiple tokens? Comma-separate them.)

### 5. Deploy

```bash
fly deploy
```

When it finishes, `fly status` shows the `*.fly.dev` hostname. Try it:

```bash
curl -i https://ridgeline-minisuite.fly.dev/ui/journalEntries
curl -i -H "Authorization: Bearer <your-token>" \
  https://ridgeline-minisuite.fly.dev/services/rest/record/v1/account
```

### 6. Add the Cloudflare subdomain

In **Cloudflare → your domain → DNS → Records**, add:

| Type | Name | Content | Proxy status |
|---|---|---|---|
| CNAME | `minisuite` | `ridgeline-minisuite.fly.dev` | **DNS only (grey cloud)** |

> **Important:** start with proxy *off* (grey cloud) so Fly can issue the TLS cert. After
> step 7 succeeds you can switch it to proxied (orange cloud) if you want Cloudflare's
> caching/firewall in front. Fly serves valid HTTPS itself either way.

### 7. Tell Fly about the custom hostname

```bash
fly certs add minisuite.yourdomain.com
fly certs show minisuite.yourdomain.com
```

It'll show `Issued` within ~30 seconds once DNS has propagated. Now hit:
- **UI:** `https://minisuite.yourdomain.com/`
- **Swagger:** `https://minisuite.yourdomain.com/docs`
- **API:** `https://minisuite.yourdomain.com/services/rest/record/v1/...`

### 8. (Optional) Turn the Cloudflare proxy back on

Flip the DNS record to proxied (orange cloud). In **SSL/TLS → Overview**, set encryption
mode to **Full (strict)** — Fly's cert is real, not self-signed. Anything less will work
but is downgraded.

---

## Option B — Render.com (simplest, but sleeps)

Render's free web service tier sleeps after 15 minutes of inactivity and has no persistent
disk. Our seed is idempotent and writes to `/tmp`, so the DB rebuilds in ~1 second on each
cold start. Fine for a demo if a 30-second first-request lag is acceptable.

1. Push this folder to a GitHub repo.
2. In Render: **New → Blueprint**, point at the repo. Render reads `render.yaml`.
3. After build/deploy, Render gives you `https://ridgeline-minisuite.onrender.com`.
4. **Settings → Custom Domains → Add Custom Domain** → `minisuite.yourdomain.com`. Render
   shows you a CNAME target like `<service>.onrender.com`.
5. In Cloudflare DNS, add CNAME `minisuite` → that target, **grey cloud**, until Render
   marks it verified. Then flip to orange if you want.

Set the token under **Environment**: `MINISUITE_TOKEN=<your-token>`.

---

## Option C — Cloudflare Tunnel (zero cloud cost)

If you have a machine that's always on (home server, mini PC, Raspberry Pi, even a
laptop that stays awake), `cloudflared` gives you a public HTTPS URL on your own subdomain
with no cloud bill at all.

### 1. Run MiniSuite locally

```bash
python -m app.seed
python -m app.main
# now listening on http://127.0.0.1:8000
```

### 2. Install `cloudflared` and authenticate

```bash
# macOS: brew install cloudflared
# Windows: winget install --id Cloudflare.cloudflared
# Linux: see https://pkg.cloudflare.com
cloudflared tunnel login
```

A browser opens; pick the Cloudflare zone for your domain.

### 3. Create a tunnel + DNS record + run it

```bash
cloudflared tunnel create minisuite
cloudflared tunnel route dns minisuite minisuite.yourdomain.com
cloudflared tunnel --url http://localhost:8000 run minisuite
```

That third command runs it in the foreground. To install as a service:

```bash
cloudflared tunnel --config ~/.cloudflared/config.yml service install
```

A minimal `~/.cloudflared/config.yml`:

```yaml
tunnel: minisuite
credentials-file: /Users/you/.cloudflared/<UUID>.json
ingress:
  - hostname: minisuite.yourdomain.com
    service: http://localhost:8000
  - service: http_status:404
```

Now `https://minisuite.yourdomain.com` reaches your local server, with TLS handled by
Cloudflare.

---

## Using the API once it's live

Anywhere the README says `http://127.0.0.1:8000`, swap in `https://minisuite.yourdomain.com`.
Otherwise the API is identical — same paths, same Bearer header, same payload shapes.

```bash
export BASE=https://minisuite.yourdomain.com
export TOKEN=<your-deployed-token>

# Pull the chart of accounts
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/services/rest/record/v1/account?limit=100" | python -m json.tool

# Post the April accrual JE
curl -i -X POST "$BASE/services/rest/record/v1/journalEntry" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tranDate": "2026-04-30",
    "reversalDate": "2026-05-01",
    "memo": "April 2026 freight accrual",
    "line": { "items": [
      { "account": { "id": "<FREIGHT_ID>" }, "debit":  90000 },
      { "account": { "id": "<ACCRUED_ID>" }, "credit": 90000 }
    ]}
  }'
```

### Pointing a real-NetSuite-shaped Python client at the deployment

```python
import os, httpx
BASE = os.environ["NS_BASE"]              # https://minisuite.yourdomain.com
TOKEN = os.environ["NS_TOKEN"]

s = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {TOKEN}"})
accounts = s.get("/services/rest/record/v1/account", params={"q": 'acctNumber EQUALS "6011"'}).json()
freight_id = accounts["items"][0]["id"]

# When ready to go to real NetSuite, change NS_BASE to
# https://<accountId>.suitetalk.api.netsuite.com and swap TOKEN for the real bearer.
# Everything else stays identical.
```

### Running the smoke test against the live URL

```bash
python smoke.py --base https://minisuite.yourdomain.com --token <your-deployed-token>
```

You should see `13 passed, 0 failed`.

### Viewing the UI in a browser

- Home: `https://minisuite.yourdomain.com/`
- Journal Entries: `https://minisuite.yourdomain.com/ui/journalEntries`
- Swagger: `https://minisuite.yourdomain.com/docs`
- OpenAPI JSON: `https://minisuite.yourdomain.com/openapi.json`

---

## Troubleshooting

**Cloudflare shows "Error 1014: CNAME Cross-User Banned"** — the target hostname is on a
Cloudflare account that has CNAME flattening disabled. Use a plain `CNAME` with the orange
cloud OFF, or use Cloudflare's "CNAME Setup" if you control the upstream account.

**Fly cert stuck on `Awaiting configuration`** — DNS hasn't propagated yet, or the
record is proxied (orange cloud). Set it to "DNS only" until the cert is `Issued`, then
flip back.

**Render cold start takes 30s+** — that's the free tier. The first request after sleep
spins up a new container and runs the seed. Subsequent requests are fast until it sleeps
again.

**SQLite file lost after deploy on Fly** — the volume isn't mounted. Run `fly volumes
list` and confirm `minisuite_data` exists and `fly.toml` references it. The Dockerfile
defaults `MINISUITE_DB=/data/minisuite.sqlite` which the volume mounts at.

**401 on every request** — check the `MINISUITE_TOKEN` env var matches the Bearer you're
sending. The dev default is `demo-token-ridgeline`. Change it in production with
`fly secrets set MINISUITE_TOKEN=...` or Render's env vars UI.
