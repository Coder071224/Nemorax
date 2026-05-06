# Android APK Build

Nemis can be packaged as an Android APK with the Flet CLI. The APK contains the Flet frontend only. It connects to the deployed FastAPI backend over HTTPS.

## What Is Packaged

- Flet entry point: `app.py`
- Frontend package: `src/nemorax/frontend`
- Public assets: `assets/`
- Public backend API URL: `https://nemorax-backend-c1ma.onrender.com`

The APK must not contain backend secrets. Supabase service role keys, Groq keys, Gemini keys, and embedding keys stay only in the backend deployment environment.

## Prerequisites

- Windows PowerShell
- Project dependencies installed in `.venv`
- Flet build prerequisites for Android installed by the Flet CLI
- Windows Developer Mode enabled for Flutter plugin symlinks
- Android phone with USB debugging enabled, or an Android emulator

Open Developer Mode settings with:

```powershell
start ms-settings:developers
```

Enable `Developer Mode`, then rerun the APK build command.

If PowerShell blocks `.venv\Scripts\Activate.ps1`, you can still build with the command below. The script directly uses `.venv\Scripts\flet.exe` when it exists, so activation is not required for APK packaging.

The script detects Java, Flutter, and the Android SDK at common Windows paths. It also installs the Android SDK packages Flutter needs for APK builds when they are missing:

```text
platform-tools
platforms;android-36
build-tools;36.0.0
```

Common SDK paths include:

```text
C:\Users\<you>\Android\sdk
C:\Users\<you>\AppData\Local\Android\Sdk
```

## Build The APK

From the project root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_android_apk.ps1
```

To clear the Flet/Flutter build cache:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_android_apk.ps1 -ClearCache
```

To build against another public backend URL:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_android_apk.ps1 -ApiUrl "https://your-backend.example.com"
```

## Output Location

The APK is written under:

```text
build\apk\
```

The exact APK filename is produced by Flet/Flutter and can vary by Flet version and build options. Look for a file ending in:

```text
.apk
```

## Install On Android

Connect the phone with USB debugging enabled, then run:

```powershell
adb devices
```

Install the generated APK:

```powershell
adb install -r .\build\apk\<apk-file-name>.apk
```

If PowerShell tab completion is available, type:

```powershell
adb install -r .\build\apk\
```

then press `Tab` until the APK file is selected.

## Runtime Backend URL

The Android build defaults to:

```text
https://nemorax-backend-c1ma.onrender.com
```

This is a public backend URL and is safe to include in the APK. Secrets are not safe to include in the APK because users can extract files from installed Android apps.

## Production Checks

Before building or sharing an APK, confirm backend health:

```powershell
Invoke-RestMethod https://nemorax-backend-c1ma.onrender.com/api/health | ConvertTo-Json -Depth 10
```

Expected backend state:

```text
status = ok
provider_available = true
knowledge_base.chunk_count = 419
knowledge_base.embedding_status = ready
knowledge_base.vector_search_function_available = true
```
