# Railway Fallback Notes

Render is the primary hosting target for Nemorax now. Keep Railway only if you
intentionally want a temporary fallback backend URL while Render is waking or
being repaired.

The landing/download website is deployed separately from `website/` on Vercel.

## Optional backend API fallback service

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

## Optional Flet web app service

Use the repository root as the service root.
This must be a separate Railway service from the backend because Railway gives
each service its own public port.

Start command:

```bash
python railway_web.py
```

Required variables:

- `NEMORAX_API_URL`

Set `NEMORAX_API_URL` to the Railway public URL of the backend API service only
if this Railway-hosted Flet app is intentionally active.
Railway provides `PORT`; both launchers default to port `8000` for local use.

For the Render-hosted Flet app, put the Railway backend URL in
`NEMORAX_API_FALLBACK_URLS` instead. Render remains the primary
`NEMORAX_API_URL`.

## Important

Both Railway services must install the root `requirements.txt`. The `nixpacks.toml`
file in this repo makes that explicit so `flet` and `flet-web` are installed before
the Flet web app starts.
