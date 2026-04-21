# Nemorax

Nemorax is a Flet frontend with a FastAPI backend for the Nemis campus assistant. The backend is structured around services, repositories, and a provider-neutral LLM adapter so the app can run on Groq by default and still switch to other OpenAI-compatible providers with minimal code changes.

Production deployment is now split as follows:

- Static website / download portal: Vercel (`website/`)
- Persistent API backend: Oracle Cloud Always Free VM
- Optional browser-based Flet app: Oracle Cloud VM behind Nginx

## Current layout

```text
NEMORAXS/
|-- app.py
|-- run.py
|-- requirements.txt
|-- pyproject.toml
|-- .env.example
|-- assets/
|-- config/
|-- data/
|-- scripts/
|-- src/
|   `-- nemorax/
|       |-- backend/
|       |   |-- api/
|       |   |-- core/
|       |   |-- llm/
|       |   |-- repositories/
|       |   |-- services/
|       |   |-- main.py
|       |   `-- schemas.py
|       |-- frontend/
|       `-- kb/
`-- tests/
```

## Backend architecture

- `backend/api/`: FastAPI app factory, dependencies, and route modules.
- `backend/core/`: settings, logging, and application error types.
- `backend/llm/`: provider interface plus concrete adapters for Groq and other OpenAI-compatible backends.
- `backend/repositories/`: Supabase-backed persistence for users, chat history, feedback, and KB access.
- `backend/services/`: business logic for auth, chat, prompt construction, history, and feedback.

The rest of the app talks to `ChatService`, not directly to a specific model vendor. Provider selection is controlled by environment variables.

## Runtime config contract

Use these canonical variables:

- `NEMORAX_ENV`: `development`, `production`, or `test`
- `NEMORAX_API_URL`: frontend-facing backend API base URL
- `BACKEND_HOST`: backend bind host
- `BACKEND_PORT`: backend bind port for local/manual runs
- `PORT`: deployment-provided bind port override
- `CORS_ORIGINS`: comma-separated frontend origins; set exact origins in production
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `NEMORAX_KB_SOURCE`
- `LLM_*`

Legacy duplicates such as `SUPABASE_ANON_KEY` and provider-specific `GROQ_*` shortcuts are no longer part of the supported config surface.

## Provider switching

The backend supports two provider modes through `LLM_PROVIDER`:

- `groq`
- `openai_compatible`

Examples:

```env
LLM_PROVIDER=groq
LLM_MODEL=openai/gpt-oss-20b
LLM_FALLBACK_MODEL=llama-3.1-8b-instant
LLM_TEMPERATURE=0.25
LLM_TOP_P=1.0
LLM_MAX_COMPLETION_TOKENS=900
LLM_REASONING_EFFORT=medium
LLM_INCLUDE_REASONING=false
LLM_STREAM=true
LLM_SEED=7
LLM_API_KEY=your-key
```

```env
LLM_PROVIDER=openai_compatible
LLM_MODEL=gpt-4o-mini
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your-key
```

## Development setup

### 1. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Create your environment file

```bash
cp .env.example .env
```

Windows CMD:

```bat
copy .env.example .env
```

### 4. Run the backend

```bash
python -m uvicorn nemorax.backend.main:app --app-dir src --reload
```

Swagger UI:

- `http://127.0.0.1:8000/docs`

### 5. Run the frontend

Desktop:

```powershell
$env:NEMORAX_API_URL="http://127.0.0.1:8000"
python app.py
```

### 6. Run the full app locally

Desktop:

```bash
python run.py
```

Web:

```powershell
$env:NEMORAX_API_URL="http://127.0.0.1:8000"
python run.py --web
```

## Tests

Run the current regression suite:

```bash
python -m unittest discover -s tests -v
```

## Deployment notes

- `run.py` is for local development convenience.
- Production backend entrypoint is `nemorax.backend.main:app`.
- Keep secrets in environment variables, not in source files.
- Set `NEMORAX_API_URL` explicitly for deployed frontends.
- Set `CORS_ORIGINS` explicitly in production.
- Recommended production split:
  - Vercel for `website/`
  - Oracle Cloud Always Free for the FastAPI backend
  - Oracle Cloud for the Flet web runtime if you need the browser app, because Flet requires a persistent Python service and is not a good fit for Cloudflare Pages or Vercel serverless hosting
- Development defaults already allow the common local frontend origins:
  - `http://127.0.0.1:8550`
  - `http://localhost:8550`
  - `http://127.0.0.1:3000`
  - `http://localhost:3000`
  - `http://127.0.0.1:5173`
  - `http://localhost:5173`
- Persistent app data and runtime KB data are stored in Supabase.
- Legacy app JSON can be imported with `python -m nemorax.backend.migrate_legacy_storage --root data`.
- Legacy KB artifacts can be imported with `python -m nemorax.backend.migrate_kb_to_supabase --kb-root kb --data-root data`.
- Structured NEMSU KB ingestion is available with `python -m nemorax.backend.ingest_nemsu_kb --max-pages 180`.
- Apply `supabase/migrations/202604140004_nemsu_structured_kb.sql` before running the structured KB ingest command.
