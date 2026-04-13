# Nemorax Deployment Guide

## Current readiness

- Local backend tests pass.
- Groq is the active provider with a fallback model.
- The public website can be bundled for static hosting.
- GitHub Actions workflows are included for CI, website deploy, and release builds.

## Persistence

Persistent app data and KB runtime data now live in Supabase. Apply both SQL migrations in `supabase/migrations/` before deploying the backend, then run the import scripts if you need to migrate legacy local data.

## 1. Push code to GitHub

1. Initialize Git locally if this folder is not yet a repository.
2. Create a GitHub repository.
3. Push the project to the default branch, ideally `main`.

## 2. Deploy the FastAPI backend

Recommended free-first path: Render.

- `render.yaml` is included.
- Backend entrypoint is `python -m uvicorn nemorax.backend.main:app --app-dir src --host 0.0.0.0 --port $PORT`
- Health check path is `/api/health`

## 3. Add production environment variables

Set these in the Render service:

- `BACKEND_URL`
- `CORS_ORIGINS`
- `LLM_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

Review and keep:

- `LLM_PROVIDER=groq`
- `LLM_MODEL=openai/gpt-oss-120b`
- `LLM_FALLBACK_MODEL=llama-3.1-8b-instant`
- `LLM_BASE_URL=https://api.groq.com/openai/v1`
- `LLM_PROMPT_KNOWLEDGE_CHARS=6000`
- `NEMORAX_KB_SOURCE=supabase`

## 4. Test the live API

Check health:

```bash
curl https://your-backend-domain/api/health
```

Expected:

- status is `ok`
- provider name is `groq`
- provider is configured

Use a very small chat prompt for first live validation to avoid unnecessary Groq usage.

## 5. Deploy the website / download portal

Recommended path: GitHub Pages.

- Workflow: `.github/workflows/website-pages.yml`
- The workflow publishes `website/`

## 6. Deploy the Flet web frontend

Recommended free-first path: Render as a second web service.

- `render.yaml` now includes `nemorax-web`
- frontend entrypoint is `python serve_web.py`
- expected URL is `https://nemorax-web.onrender.com`

After creating or syncing the Blueprint:

- confirm the `nemorax-web` service is created
- keep `BACKEND_URL=https://nemorax-backend.onrender.com`
- update the backend `CORS_ORIGINS` to include both:
  - `https://coder071224.github.io`
  - `https://nemorax-web.onrender.com`

Then open:

```bash
https://nemorax-web.onrender.com
```

The public website web-app button is intended to point to that frontend URL.

## 7. Connect a custom domain

For GitHub Pages:

1. Set Pages source to GitHub Actions.
2. Add your custom domain in repository Pages settings.
3. Add the DNS records requested by GitHub.
4. If you want the custom domain tracked in source, add a `CNAME` file directly inside `website/`.

## 8. Build EXE / APK with Flet

Release workflow:

- `.github/workflows/release-build.yml`

Outputs:

- Windows zip artifact
- Android APK

Before relying on release automation, verify that the chosen Flet CLI version in CI still matches the project.

## 9. Upload builds to GitHub Releases

This is handled by the release workflow when a GitHub Release is published.

## 10. Connect download buttons to release files

Edit `website/assets/js/site-config.js`:

- set `github.owner`
- set `github.repo`
- optionally set `github.releaseTag`
- confirm asset names:
  - `Nemorax.exe`
  - `Nemorax.apk`

The website then generates direct GitHub release download links automatically.

## Final checks

- rotate the Groq API key before public deployment if it has been exposed
- replace `CORS_ORIGINS=*` with exact production origins
- verify live website links after the first release is published
