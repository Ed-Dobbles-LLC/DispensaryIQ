# DispensaryIQ — pitch site (Railway-deployable)

Static HTML, served by Caddy in a 12 MB Alpine container. Deploys to Railway in ~2 minutes.

## Repo layout

```
dispensaryiq-pitch/
├── Dockerfile              Caddy 2.8 alpine, copies /site to /srv
├── Caddyfile               Static server config (port from $PORT env)
├── railway.json             Tells Railway to use the Dockerfile
├── .dockerignore           Skip docs/git in image
├── .gitignore              Skip OS/IDE files
└── site/
    ├── index.html          Landing
    ├── coverage.html       Report 01
    ├── robots.txt          Disallow indexing
    └── assets/             style.css · disps.js · montserrat-700.woff2
```

---

## Deploy steps (PowerShell)

### 1. Create the GitHub repo

In a browser at https://github.com/organizations/Ed-Dobbles-LLC/repositories/new:
- **Repository name:** `dispensaryiq-pitch`
- **Visibility:** Private (the URL will be unlisted, but private repo is belt-and-suspenders)
- **Do not** initialize with README/license/.gitignore — we have those locally

Click **Create repository.**

### 2. Push the bundle

```powershell
# Replace path if you saved the bundle elsewhere
cd "C:\Users\eddob\Claude Projects\Repos"

# Clone the empty repo
git clone https://github.com/Ed-Dobbles-LLC/dispensaryiq-pitch.git
cd dispensaryiq-pitch

# Copy the deploy bundle in
# (Drag-and-drop from the Claude output folder into this dir,
#  or use Copy-Item if you prefer):
Copy-Item -Recurse -Path "$env:USERPROFILE\Downloads\dispensaryiq-pitch\*" -Destination . -Force

# Commit
git add .
git commit -m "feat: dispensaryiq pitch site v1 — coverage report"
git push origin main
```

### 3. Connect to Railway

In a browser at https://railway.app:

1. **New Project → Deploy from GitHub repo**
2. Select **`Ed-Dobbles-LLC/dispensaryiq-pitch`**
3. Railway detects the `Dockerfile` and starts building automatically
4. Once it shows "Active," go to **Settings → Networking → Generate Domain**
5. Railway gives you a `*.up.railway.app` URL — that's the live site

The first build takes ~90 seconds. Subsequent pushes auto-deploy on every `git push` to main.

### 4. Smoke-test

Open the Railway URL. You should see:
- Landing page loads instantly with the navy nav and six report cards
- Click **Data coverage** — map renders the current certified dispensary cohort (active 1,136 / full 1,139), hover works, no network errors in DevTools
- View source: no external HTTP refs (all assets served from `/assets/*`)

---

## Iterating after deploy

To update the site:

```powershell
cd "C:\Users\eddob\Claude Projects\Repos\dispensaryiq-pitch"
# Edit files in site/
git add site/
git commit -m "update: <change description>"
git push origin main
```

Railway auto-redeploys in ~60 seconds.

---

## Adding auth (optional, ~5 min)

If you want to gate the URL with a username/password before sharing externally — add to `Caddyfile`, replace the existing `:{$PORT:8080} { ... }` block with:

```
:{$PORT:8080} {
	basicauth {
		curaleaf JDJhJDEyJC4uLg==   # ← bcrypt hash, see below
	}
	root * /srv
	encode gzip zstd
	file_server
	header X-Robots-Tag "noindex, nofollow"
}
```

To generate the hash, in PowerShell once Caddy is in your container:

```powershell
# Run a throwaway Caddy container to hash a password
docker run --rm caddy:2.8-alpine caddy hash-password --plaintext "your-password-here"
```

Paste the resulting hash where the placeholder is, commit, push. Railway redeploys with auth enforced.

---

## Custom domain (optional)

In Railway: **Settings → Networking → Custom Domain → Add `pitch.dispensaryiq.com`** (or whatever).
Then add a CNAME in your DNS pointing to the value Railway shows. HTTPS auto-provisioned by Railway.

---

## Cost on Railway

This container is tiny (12 MB Caddy + 344 KB site). On Railway Pro it runs in the included compute — effectively free. If it idles ($PORT not hit), Railway sleeps it; first visitor wakes it in ~3 seconds.

---

## Cleanup if you change your mind

Railway: **Settings → Danger → Delete Service** — kills the deploy and stops charges. The GitHub repo is unaffected.
