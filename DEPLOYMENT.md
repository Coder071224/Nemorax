# Nemorax Deployment Guide

This repo uses a static frontend on Vercel and persistent Python services on Oracle Cloud Always Free.

## Target production topology

- `website/` -> Vercel static site
- FastAPI backend -> Oracle Cloud Always Free VM as a persistent `systemd` service
- Optional Flet browser app -> same Oracle VM as a persistent `systemd` service behind Nginx

This is the safest migration path because:

- Vercel serves the static website for free without sleeping
- Oracle Always Free can keep the Python backend online continuously
- The Flet web app keeps its existing behavior on Oracle instead of being forced into an incompatible serverless host

## Files added for the new deployment

- `website/vercel.json`
- `deploy/oracle/backend/nemorax-backend.service`
- `deploy/oracle/frontend/nemorax-web.service`
- `deploy/oracle/env/backend.env.example`
- `deploy/oracle/env/web.env.example`
- `deploy/oracle/nginx/nemorax.conf`

## Legacy deployment files removed

- `.github/workflows/website-pages.yml`

## Production domains

Use three explicit origins:

- `https://nemorax.vercel.app` or your Vercel custom domain for the public website
- `https://api.nemorax.example.com` for FastAPI
- `https://app.nemorax.example.com` for the browser-based Flet app if you want web access to the full app

## 1. Prepare Supabase

Apply the migrations in `supabase/migrations/` before deploying the backend.

If you need to migrate older local data:

```bash
python -m nemorax.backend.migrate_legacy_storage --root data
python -m nemorax.backend.migrate_kb_to_supabase --kb-root kb --data-root data
```

## 2. Provision the Oracle Cloud Always Free VM

Recommended baseline:

- Ubuntu 24.04
- 1 public IP
- ports `80` and `443` open in the Oracle security list

Install runtime packages:

```bash
sudo apt update
sudo apt install -y python3 python3-venv nginx
```

Clone the repo and install dependencies:

```bash
sudo mkdir -p /opt/nemorax
sudo chown $USER:$USER /opt/nemorax
git clone https://github.com/<your-account>/<your-repo>.git /opt/nemorax/NEMORAXS
cd /opt/nemorax/NEMORAXS
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 3. Create backend and web env files on Oracle

Backend:

```bash
sudo mkdir -p /etc/nemorax
sudo cp deploy/oracle/env/backend.env.example /etc/nemorax/backend.env
sudo nano /etc/nemorax/backend.env
```

Required backend values:

- `NEMORAX_ENV=production`
- `NEMORAX_API_URL=https://api.nemorax.example.com`
- `CORS_ORIGINS=https://nemorax.vercel.app,https://app.nemorax.example.com`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `LLM_API_KEY`

Optional browser app env:

```bash
sudo cp deploy/oracle/env/web.env.example /etc/nemorax/web.env
sudo nano /etc/nemorax/web.env
```

Keep:

- `NEMORAX_API_URL=https://api.nemorax.example.com`
- `FLET_SERVER_IP=127.0.0.1`
- `FLET_SERVER_PORT=8550`

## 4. Install the Oracle services

```bash
sudo cp deploy/oracle/backend/nemorax-backend.service /etc/systemd/system/
sudo cp deploy/oracle/frontend/nemorax-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable nemorax-backend
sudo systemctl enable nemorax-web
sudo systemctl start nemorax-backend
sudo systemctl start nemorax-web
```

Check both services:

```bash
sudo systemctl status nemorax-backend
sudo systemctl status nemorax-web
```

## 5. Configure Nginx on Oracle

Copy the provided config and replace the example hostnames:

```bash
sudo cp deploy/oracle/nginx/nemorax.conf /etc/nginx/sites-available/nemorax
sudo nano /etc/nginx/sites-available/nemorax
sudo ln -s /etc/nginx/sites-available/nemorax /etc/nginx/sites-enabled/nemorax
sudo nginx -t
sudo systemctl reload nginx
```

The Nginx file routes:

- `api.nemorax.example.com` -> `127.0.0.1:8000`
- `app.nemorax.example.com` -> `127.0.0.1:8550`

After DNS is live, add TLS with Certbot or your preferred ACME client.

## 6. Deploy the static website on Vercel

Vercel setup:

1. Import the GitHub repository into Vercel.
2. Set the Vercel Root Directory to `website`.
3. Leave the framework preset as `Other`.
4. Deploy.

`website/vercel.json` already enables clean URLs and basic security headers.

After the first Vercel deploy, edit `website/assets/js/site-config.js` and set:

- `github.owner`
- `github.repo`
- `app.webUrl=https://app.nemorax.example.com`

Then redeploy the `website/` project on Vercel.

## 7. Validate frontend-to-backend connectivity

Backend health:

```bash
curl https://api.nemorax.example.com/api/health
```

Expected result:

- response envelope has `ok: true`
- `provider.available` is `true`

Browser app validation:

1. Open `https://app.nemorax.example.com`
2. Sign in or create a test account
3. Send a short prompt
4. Confirm chat history and feedback still persist

Website validation:

1. Open the Vercel site
2. Confirm the download cards render
3. Confirm the "Open web app" button points to `https://app.nemorax.example.com`

## 8. Release builds

The release workflow for Windows and Android remains in `.github/workflows/release-build.yml`.

That workflow is independent from the hosting migration and can stay as-is.

## Final production checklist

- no legacy PaaS-specific deployment config remains
- `NEMORAX_API_URL` is the only supported frontend API base URL variable
- `CORS_ORIGINS` contains exact production origins only
- backend and optional Flet web runtime both restart under `systemd`
- public website is static on Vercel and does not go offline after inactivity
