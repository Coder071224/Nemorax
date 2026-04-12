# Nemorax

Nemorax is a Flet frontend with a FastAPI backend for the Nemis campus assistant. The backend is structured around services, repositories, and a provider-neutral LLM adapter so the app can run on Groq by default and still switch to other OpenAI-compatible providers with minimal code changes.

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
- `backend/repositories/`: file-backed persistence for users, chat history, and feedback.
- `backend/services/`: business logic for auth, chat, prompt construction, history, and feedback.

The rest of the app talks to `ChatService`, not directly to a specific model vendor. Provider selection is controlled by environment variables.

## Provider switching

The backend supports three provider modes through `LLM_PROVIDER`:

- `groq`
- `openai_compatible`

Examples:

```env
LLM_PROVIDER=groq
LLM_MODEL=openai/gpt-oss-120b
LLM_FALLBACK_MODEL=llama-3.1-8b-instant
GROQ_API_KEY=your-key
```

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

```bash
python app.py
```

### 6. Run the full app locally

Desktop:

```bash
python run.py
```

Web:

```bash
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
- Set `CORS_ORIGINS` explicitly in production.
- File-backed persistence works for a single deployment target today, but the repository/service split makes moving to a database later straightforward.
