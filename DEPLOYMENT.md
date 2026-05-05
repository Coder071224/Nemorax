# Deployment

Target deployment split:

- Backend/API: Railway
- Flet web app/frontend: Railway
- Landing/download website: Vercel
- Source control and release artifacts: GitHub

## Backend API on Railway

Create a Railway service from the repository root.

Start command:

```bash
python railway_backend.py
```

The backend listens on Railway's `PORT` variable and defaults to `8000` for local
development.

Required Railway variables:

- `NEMORAX_ENV=production`
- `ALLOWED_ORIGINS`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `LLM_API_KEY`

Optional variables are documented in `.env.example`.

## Flet web app on Railway

Create a second Railway service from the repository root.

Start command:

```bash
python railway_web.py
```

Set:

- `NEMORAX_ENV=production`
- `NEMORAX_API_URL=<public Railway backend URL>`

The Flet web app also listens on Railway's `PORT` variable and defaults to
`8000` for local development. It should run as its own Railway service, not in
the same process as the backend API.

## Landing/download website on Vercel

Create a Vercel project with root directory:

```text
website
```

The Vercel config is `website/vercel.json`. Update
`website/assets/js/site-config.js` when Railway service URLs or GitHub release
asset names change.

## Local smoke checks

Backend:

```bash
python railway_backend.py
```

Flet web app:

```bash
$env:NEMORAX_API_URL="http://127.0.0.1:8000"
python railway_web.py
```

Landing site:

Open `website/index.html` directly, or serve the `website/` folder with any
static file server.
