# Deployment

Target deployment split:

- Backend/API: Render
- Flet web app/frontend: Render, if you want browser access through a Python Flet server
- Landing/download website: Vercel (`website/`)
- Source control and release artifacts: GitHub
- Database and runtime persistence: Supabase, if already used by the project

Railway can be kept only as an optional fallback backend URL while Render is the primary host.

## Render Dashboard Notes

Create new Render services from scratch instead of relying on old suspended services:

- `nemorax-backend`
- `nemorax-flet-web`, only if the Flet web app is hosted as a separate Python web service

Before deleting any old suspended Render service, open its Environment settings and copy any needed variable values into your own secure notes or directly into the new Render service. Do not paste secrets into Codex, ChatGPT, docs, commits, screenshots, or issue comments. Secrets such as API keys, Supabase keys, database URLs, and tokens belong only in Render Environment settings or another secret manager.

## Backend API on Render

Create a Render Web Service from the repository root.

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
python -m uvicorn nemorax.backend.main:app --app-dir src --host 0.0.0.0 --port $PORT
```

Render provides `PORT` in production. Local development still defaults to port `8000`.

Required Render variables:

- `NEMORAX_ENV=production`
- `ALLOWED_ORIGINS`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `LLM_API_KEY`

Optional variables are documented in `.env.example`.

Health check path:

```text
/api/health
```

## Flet Web App on Render

Create a second Render Web Service from the repository root only if you want the Flet browser app hosted separately from the landing site.

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
python serve_web.py
```

Set:

- `NEMORAX_ENV=production`
- `NEMORAX_API_URL=https://nemorax-backend.onrender.com`
- `NEMORAX_API_FALLBACK_URLS=<optional Railway backend URL>`

The Flet service reads Render's `PORT` in production and falls back to `8000` locally. Do not deploy Flet as static-only unless the app is explicitly changed for that later.

## Landing/download website on Vercel

Create or keep a Vercel project with root directory:

```text
website
```

The Vercel config is `website/vercel.json`. Update `website/assets/js/site-config.js` when the Render service URLs or GitHub release asset names change.

## Local smoke checks

Backend:

```bash
python -m uvicorn nemorax.backend.main:app --app-dir src --reload --host 0.0.0.0 --port 8000
```

Flet web app:

```bash
$env:NEMORAX_API_URL="http://127.0.0.1:8000"
python serve_web.py
```

Landing site:

Open `website/index.html` directly, or serve the `website/` folder with any static file server.
