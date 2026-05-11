# Windows EXE Build

Nemis can be packaged as a Windows desktop executable with the Flet CLI. The
Windows build contains the Flet frontend, public assets, and public backend URL
configuration. It must not contain backend secrets.

## What Is Packaged

- Flet entry point: `app.py`
- Frontend package: `src/nemorax/frontend`
- Public assets: `assets/`
- Public backend API URL: `https://nemorax-backend-c1ma.onrender.com`

Backend-only files, local environment files, tests, deployment config, and build
artifacts are excluded by the build script.

## Prerequisites

- Windows PowerShell
- Project dependencies installed in `.venv`
- Flet CLI available from `.venv\Scripts\flet.exe` or `PATH`
- Windows desktop build prerequisites required by Flutter/Flet

If dependencies are missing, run from the project root:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
```

## Build The EXE

From the project root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows_exe.ps1
```

To clear the Flet/Flutter build cache:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows_exe.ps1 -ClearCache
```

To build against another public backend URL:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows_exe.ps1 -ApiUrl "https://your-backend.example.com"
```

## Output Location

The build output is written under:

```text
build\windows\
```

Look for:

```text
build\windows\Nemis.exe
```

Depending on the Flet/Flutter version, the executable may be inside a nested
runner or release folder under `build\windows\`.

## Secret Safety

Do not put Supabase service role keys, Groq keys, Gemini keys, Railway tokens,
or any private credentials in `app.py`, `src/nemorax/frontend`, assets, or build
scripts. The Windows app should only use public frontend configuration and call
the deployed backend over HTTPS.
