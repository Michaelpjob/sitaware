# Setup — shipping the tracker to friends & family

End-state: a public dashboard at `https://tracker.yourdomain.com` that refreshes
weekly, sends you an email when a new 13F lands, and lets friends subscribe for
quarterly alerts.

Total out-of-pocket: a domain (~$12/year). Everything else is free tier.

Rough order (40-60 min end to end):

1. [Push to GitHub](#1-github--pages) → get a live `*.github.io` URL
2. [Register a domain](#2-domain) → point it at Pages
3. [Set up Resend](#3-resend) → verified sender + audience for signups
4. [Deploy the subscribe Worker](#4-cloudflare-worker) → wires up the signup form
5. [Set GitHub repo variables](#5-repo-variables) → bakes the URLs into the build

---

## 1. GitHub + Pages

```bash
cd /c/Users/micha/Desktop/situational-awareness-tracker
git init -b main
git add .
git commit -m "initial import"
gh repo create situational-awareness-tracker --public --source=. --push
```

Then in the repo settings:

- **Settings → Pages**: source = `Deploy from a branch`, branch = `main`, folder = `/docs`. Save.
- **Settings → Secrets and variables → Actions → Secrets** → add:
  - `SEC_USER_AGENT` = `"Your Name (your@email.com)"` — SEC requires this.
- **Actions tab**: run the `Weekly 13F check` workflow once manually (workflow_dispatch) to confirm it produces a fresh `docs/index.html` and commits it.

After a minute or two, the dashboard will be live at `https://<your-gh-username>.github.io/situational-awareness-tracker/`.

## 2. Domain

Register something like `tracker.yourdomain.com` or pick a standalone name. Any registrar works — Cloudflare, Namecheap, Porkbun are all fine. Cloudflare is the easiest here since the Worker also lives there.

**If you register at Cloudflare**:

1. Add the domain to Cloudflare (follow the name-server migration steps if registering elsewhere).
2. In **DNS**, add a CNAME record: `tracker` → `<your-gh-username>.github.io`. Proxy status = DNS only (gray cloud) for GitHub Pages, Proxied (orange) is also fine.
3. In the repo, **Settings → Pages → Custom domain** = `tracker.yourdomain.com`. Check "Enforce HTTPS" once the cert provisions (5-10 min).
4. Write `tracker.yourdomain.com` into `docs/CNAME` so GitHub Pages preserves it on redeploys:
   ```bash
   echo "tracker.yourdomain.com" > docs/CNAME
   git add docs/CNAME && git commit -m "Add CNAME" && git push
   ```

## 3. Resend

[resend.com](https://resend.com) → Sign up (free tier: 3k emails/month, 1 audience). You'll use it for two things: alert emails to you + subscriber management for friends.

1. **Add + verify a domain** (Domains tab). Follow their DNS instructions — for Cloudflare DNS, toggle the records to "DNS only" (gray cloud) until verified. You'll get a verified sender like `alerts@yourdomain.com`.
2. **Create an API key** (API Keys tab) → copy the `re_…` value.
3. **Create an Audience** (Audiences tab) → name it e.g. "13F alerts" → copy the UUID from the URL.

Add these to the GitHub repo secrets (**Settings → Secrets and variables → Actions → Secrets**):

- `RESEND_API_KEY` = `re_…`
- `ALERT_EMAIL_FROM` = `alerts@yourdomain.com` (must be a verified sender)
- `ALERT_EMAIL_TO` = your personal inbox (for the per-filing alert, not subscribers)

## 4. Cloudflare Worker

The signup form POSTs email addresses to a tiny Worker that adds them to your Resend audience.

```bash
cd infra/subscribe-worker
npm install
npx wrangler login
```

Edit `wrangler.toml` and set `ALLOWED_ORIGIN` to your dashboard URL(s):

```toml
ALLOWED_ORIGIN = "https://tracker.yourdomain.com,https://<your-gh-username>.github.io"
```

Set the two secrets and deploy:

```bash
npx wrangler secret put RESEND_API_KEY        # paste the re_… key
npx wrangler secret put RESEND_AUDIENCE_ID    # paste the audience UUID
npx wrangler deploy
```

Wrangler prints a URL like `https://subscribe-worker.<your-account>.workers.dev`. Smoke-test:

```bash
curl -X POST https://subscribe-worker.<your-account>.workers.dev \
  -H "Origin: https://tracker.yourdomain.com" \
  -H "Content-Type: application/json" \
  -d '{"email":"you@yourdomain.com"}'
# -> {"ok":true}
```

**Optional — custom subdomain for the Worker**: in the Cloudflare dashboard, the Worker → Triggers → Custom Domains → Add `subscribe.tracker.yourdomain.com`. Uncomment the `routes` line in `wrangler.toml` and redeploy to make that stick.

## 5. Repo variables

**Settings → Secrets and variables → Actions → Variables** (not Secrets — these are baked into the HTML and therefore public). Add:

| Name | Value |
|------|-------|
| `SITE_NAME` | `Situational Awareness Tracker` |
| `SITE_URL` | `https://tracker.yourdomain.com` |
| `REPO_URL` | `https://github.com/<your-gh-username>/situational-awareness-tracker` |
| `SIGNUP_ENDPOINT` | `https://subscribe-worker.<your-account>.workers.dev` (or custom subdomain) |
| `OG_IMAGE_URL` | `https://tracker.yourdomain.com/og.png` *(create later — see below)* |

Re-run the weekly workflow manually once. The new `docs/index.html` will have your URLs baked in and the signup form wired up.

## Optional polish

- **OG image**: drop a 1200×630 PNG into `docs/og.png` (a screenshot of the dashboard works great — use the browser's "Save as image" on a zoomed-in view of the header + summary stats). Push. Test previews at [opengraph.xyz](https://www.opengraph.xyz).
- **Favicon**: already handled inline (green upward-trending line on a dark square). Replace by editing the `<link rel="icon" ...>` line in `templates/dashboard.html.j2`.
- **Tracking a second fund**: bump `--cik` in `.github/workflows/weekly-check.yml` or add a second job. The render layer already accepts a `filer_name`/`cik` per invocation.

## Troubleshooting

- **Signup form silently fails in browser**: open DevTools → Network tab → look at the subscribe POST. 403 = origin not in `ALLOWED_ORIGIN`. 500 = Resend secrets missing on the Worker.
- **Workflow commits are empty**: normal if no new filing and no price moves. Force a rerun with the "force" input.
- **Dashboard looks old in browser**: GitHub Pages caches aggressively. Hard-refresh (Ctrl-Shift-R). CDN purges in a few minutes on its own.
- **Resend won't verify the domain**: most common cause is the DNS records being proxied. Switch to "DNS only" (gray cloud) for those records — you can flip them back after verification.
