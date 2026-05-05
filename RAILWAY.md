# Railway Deployment

This repository has two Railway services from the same GitHub repo.
The landing/download website is deployed separately from `website/` on Vercel.

## Backend API service

Use the repository root as the service root.

Start command:

```bash
python railway_backend.py
```

Required variables:

- `NEMORAX_ENV`
- `ALLOWED_ORIGINS`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `LLM_API_KEY`

## Flet web app service

Use the repository root as the service root.
This must be a separate Railway service from the backend because Railway gives
each service its own public port.

Start command:

```bash
python railway_web.py
```

Required variables:

- `NEMORAX_API_URL`

Set `NEMORAX_API_URL` to the Railway public URL of the backend API service.
Railway provides `PORT`; both launchers default to port `8000` for local use.

## Important

Both Railway services must install the root `requirements.txt`. The `nixpacks.toml`
file in this repo makes that explicit so `flet` and `flet-web` are installed before
the Flet web app starts.
