param(
    [string]$ApiUrl = "https://nemorax-backend-c1ma.onrender.com",
    [string]$BuildVersion = "1.0.0",
    [string]$BuildNumber = "1",
    [switch]$ClearCache
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$FletCommand = Join-Path $ProjectRoot ".venv\Scripts\flet.exe"
if (-not (Test-Path -LiteralPath $FletCommand)) {
    $FletFromPath = Get-Command flet -ErrorAction SilentlyContinue
    if ($FletFromPath) {
        $FletCommand = $FletFromPath.Source
    }
}

if (-not (Test-Path -LiteralPath $FletCommand)) {
    throw "Flet CLI was not found. Run: .\.venv\Scripts\python.exe -m pip install -e ."
}

$env:NEMORAX_ENV = "production"
$env:NEMORAX_API_URL = $ApiUrl.TrimEnd("/")
$env:FLET_CLI_NO_RICH_OUTPUT = "1"
$env:PYTHONUTF8 = "1"

$ExcludeFiles = @(
    ".agents",
    ".claude",
    ".git",
    ".github",
    ".idea",
    ".junie",
    ".mypy_cache",
    ".pytest_cache",
    ".qwen",
    ".venv",
    ".env",
    ".env.*",
    ".gitignore",
    ".python-version",
    "__pycache__",
    "build",
    "config",
    "data",
    "deploy",
    "dist",
    "docs",
    "flet-build",
    "kb",
    "kb/**",
    "scripts",
    "supabase",
    "tests",
    "website",
    "src/nemorax/backend",
    "src/nemorax/backend/**",
    "src/nemorax/kb",
    "src/nemorax/kb/**",
    "*.aab",
    "*.apk",
    "*.appinstaller",
    "*.appx",
    "*.cer",
    "*.jks",
    "*.keystore",
    "*.log",
    "*.msix",
    "*.msixbundle",
    "*.zip",
    "DEPLOYMENT.md",
    "Procfile",
    "Procfile.frontend",
    "RAILWAY.md",
    "documents_manifest.jsonl",
    "key.properties",
    "nixpacks.toml",
    "railway.json",
    "railway_backend.py",
    "railway_web.py",
    "render.yaml",
    "requirements-backend.txt",
    "requirements-mobile.txt",
    "requirements.txt",
    "run.py",
    "serve_web.py",
    "skills-lock.json"
)

$OutputDir = Join-Path $ProjectRoot "build\windows"

$argsList = @(
    "build",
    "windows",
    ".",
    "--output",
    $OutputDir,
    "--project",
    "nemis",
    "--artifact",
    "Nemis",
    "--product",
    "Nemis",
    "--company",
    "Nemorax",
    "--org",
    "com.nemorax",
    "--description",
    "Nemis desktop app by Nemorax",
    "--copyright",
    "Copyright (c) 2026 Nemorax",
    "--build-version",
    $BuildVersion,
    "--build-number",
    $BuildNumber,
    "--compile-app",
    "--cleanup-app",
    "--cleanup-app-files"
) + $ExcludeFiles

if ($ClearCache) {
    $argsList += "--clear-cache"
}

& $FletCommand @argsList
if ($LASTEXITCODE -ne 0) {
    throw "Flet Windows build failed with exit code $LASTEXITCODE."
}

$ExeFiles = Get-ChildItem -Path $OutputDir -Recurse -Filter "Nemis.exe" -ErrorAction SilentlyContinue
if (-not $ExeFiles) {
    $ExeFiles = Get-ChildItem -Path $OutputDir -Recurse -Filter "*.exe" -ErrorAction SilentlyContinue
}

if ($ExeFiles) {
    Write-Host "Windows executable build completed:"
    $ExeFiles | ForEach-Object { Write-Host $_.FullName }
}
else {
    Write-Host "Windows build completed. Check output folder: $OutputDir"
}
