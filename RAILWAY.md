# Railway Deployment

This repository has two Railway services from the same GitHub repo.

## Backend API service

Use the repository root as the service root.

Start command:

```bash
python -m uvicorn nemorax.backend.main:app --app-dir src --host 0.0.0.0 --port $PORT
```

Required variables:

- `NEMORAX_ENV`
- `ALLOWED_ORIGINS`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `LLM_API_KEY`

## Flet web app service

Use the repository root as the service root.

Start command:

```bash
python serve_web.py
```

Required variables:

- `NEMORAX_API_URL`

Set `NEMORAX_API_URL` to the Railway public URL of the backend API service.

## Important

Both Railway services must install the root `requirements.txt`. The `nixpacks.toml`
file in this repo makes that explicit so `flet` and `flet-web` are installed before
the Flet web app starts.
