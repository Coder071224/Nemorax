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

function Test-SymlinkSupport {
    $TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("nemis-symlink-check-" + [System.Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $TempRoot | Out-Null
    try {
        $Target = Join-Path $TempRoot "target.txt"
        $Link = Join-Path $TempRoot "link.txt"
        Set-Content -Path $Target -Value "ok"
        New-Item -ItemType SymbolicLink -Path $Link -Target $Target -ErrorAction Stop | Out-Null
        return $true
    }
    catch {
        return $false
    }
    finally {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-SymlinkSupport)) {
    $DeveloperMode = $false
    try {
        $AppModelUnlock = Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock" -ErrorAction Stop
        $DeveloperMode = $AppModelUnlock.AllowDevelopmentWithoutDevLicense -eq 1
    }
    catch {
        $DeveloperMode = $false
    }

    if ($DeveloperMode) {
        throw "Windows Developer Mode is enabled, but this PowerShell session still cannot create symlinks. Close all terminals and open a new PowerShell, or sign out/restart Windows. If it still fails, run PowerShell as Administrator and rerun this script."
    }

    throw "Android builds require Windows Developer Mode for Flutter plugin symlinks. Run: start ms-settings:developers, enable Developer Mode, then rerun this script."
}

$env:NEMORAX_ENV = "production"
$env:NEMORAX_API_URL = $ApiUrl.TrimEnd("/")
$env:FLET_CLI_NO_RICH_OUTPUT = "1"
$env:PYTHONUTF8 = "1"

$JavaCandidates = @(@(
    $env:JAVA_HOME,
    (Join-Path $env:USERPROFILE "java\17.0.13+11"),
    (Join-Path $env:ProgramFiles "Android\Android Studio\jbr"),
    (Join-Path $env:ProgramFiles "Java\jdk-17")
) | Where-Object { $_ -and (Test-Path -LiteralPath (Join-Path $_ "bin\java.exe")) })

if ($JavaCandidates.Count -gt 0) {
    $JavaHomePath = $JavaCandidates[0]
    $env:JAVA_HOME = $JavaHomePath
    $env:PATH = (Join-Path $JavaHomePath "bin") + [System.IO.Path]::PathSeparator + $env:PATH
}

$FlutterCandidates = @(@(
    (Join-Path $env:USERPROFILE "flutter\3.41.4"),
    (Join-Path $env:USERPROFILE "flutter"),
    $env:FLUTTER_ROOT
) | Where-Object { $_ -and (Test-Path -LiteralPath (Join-Path $_ "bin\flutter.bat")) })

if ($FlutterCandidates.Count -gt 0) {
    $FlutterRootPath = $FlutterCandidates[0]
    $env:FLUTTER_ROOT = $FlutterRootPath
    $env:PATH = (Join-Path $FlutterRootPath "bin") + [System.IO.Path]::PathSeparator + $env:PATH
}

$AndroidSdkCandidates = @(@(
    $env:ANDROID_HOME,
    $env:ANDROID_SDK_ROOT,
    (Join-Path $env:USERPROFILE "Android\sdk"),
    (Join-Path $env:LOCALAPPDATA "Android\Sdk")
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) })

if ($AndroidSdkCandidates.Count -gt 0) {
    $AndroidSdkPath = $AndroidSdkCandidates[0]
    $env:ANDROID_HOME = $AndroidSdkPath
    $env:ANDROID_SDK_ROOT = $AndroidSdkPath
    $PlatformTools = Join-Path $AndroidSdkPath "platform-tools"
    $CmdlineTools = Join-Path $AndroidSdkPath "cmdline-tools\12.0\bin"
    $PathParts = @($PlatformTools, $CmdlineTools) | Where-Object { Test-Path -LiteralPath $_ }
    if ($PathParts.Count -gt 0) {
        $env:PATH = ($PathParts -join [System.IO.Path]::PathSeparator) + [System.IO.Path]::PathSeparator + $env:PATH
    }
}

function Ensure-AndroidSdkPackage {
    param(
        [string]$PackageName,
        [string]$InstalledPath
    )

    if (Test-Path -LiteralPath $InstalledPath) {
        return
    }

    if (-not $env:JAVA_HOME) {
        throw "Java was not found. Flet normally installs it under $env:USERPROFILE\java. Rerun the build once, then rerun this script."
    }

    $SdkManager = Join-Path $env:ANDROID_HOME "cmdline-tools\12.0\bin\sdkmanager.bat"
    if (-not (Test-Path -LiteralPath $SdkManager)) {
        throw "Android sdkmanager was not found at $SdkManager. Rerun this script so Flet can install the Android SDK command line tools."
    }

    $LicensesPath = Join-Path $env:ANDROID_HOME "licenses"
    New-Item -ItemType Directory -Path $LicensesPath -Force | Out-Null
    Set-Content -Path (Join-Path $LicensesPath "android-sdk-license") -Value @(
        "8933bad161af4178b1185d1a37fbf41ea5269c55",
        "d56f5187479451eabf01fb78af6dfcb131a6481e",
        "24333f8a63b6825ea9c5514f83c2829b004d1fee"
    )
    Set-Content -Path (Join-Path $LicensesPath "android-sdk-preview-license") -Value "84831b9409646a918e30573bab4c9c91346d8abd"

    Write-Host "Installing Android SDK package: $PackageName"
    & $SdkManager --sdk_root=$env:ANDROID_HOME $PackageName
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install Android SDK package: $PackageName"
    }
}

if ($env:ANDROID_HOME) {
    Ensure-AndroidSdkPackage "platform-tools" (Join-Path $env:ANDROID_HOME "platform-tools")
    Ensure-AndroidSdkPackage "platforms;android-36" (Join-Path $env:ANDROID_HOME "platforms\android-36")
    Ensure-AndroidSdkPackage "build-tools;36.0.0" (Join-Path $env:ANDROID_HOME "build-tools\36.0.0")
}

if ($env:FLUTTER_ROOT) {
    $FlutterCommand = Join-Path $env:FLUTTER_ROOT "bin\flutter.bat"
    if ($env:ANDROID_HOME) {
        & $FlutterCommand config --android-sdk $env:ANDROID_HOME | Out-Host
    }
    if ($env:JAVA_HOME) {
        & $FlutterCommand config --jdk-dir $env:JAVA_HOME | Out-Host
    }
}

$argsList = @(
    "build",
    "apk",
    ".",
    "--project", "nemis",
    "--product", "Nemis",
    "--org", "com.nemorax",
    "--bundle-id", "com.nemorax.nemis",
    "--company", "Nemorax",
    "--description", "Nemis campus assistant by Nemorax",
    "--build-version", $BuildVersion,
    "--build-number", $BuildNumber,
    "--android-permissions", "android.permission.INTERNET=true",
    "--android-adaptive-icon-background", "#0D0820",
    "--exclude", ".env",
    "--exclude", ".env.*",
    "--exclude", ".venv",
    "--exclude", "venv",
    "--exclude", ".git",
    "--exclude", ".idea",
    "--exclude", ".vscode",
    "--exclude", "data/HISTORY",
    "--exclude", "data/USERS",
    "--exclude", "data/FEEDBACK",
    "--exclude", "kb/raw",
    "--exclude", "build",
    "--exclude", "dist",
    "--yes"
)

if ($ClearCache) {
    $argsList += "--clear-cache"
}

Write-Host "Building Nemis Android APK..."
Write-Host "Backend API URL: $env:NEMORAX_API_URL"
if ($env:JAVA_HOME) {
    Write-Host "Java: $env:JAVA_HOME"
}
if ($env:FLUTTER_ROOT) {
    Write-Host "Flutter: $env:FLUTTER_ROOT"
}
if ($env:ANDROID_HOME) {
    Write-Host "Android SDK: $env:ANDROID_HOME"
}
Write-Host "No backend secrets are packaged into the APK."

& $FletCommand @argsList
if ($LASTEXITCODE -ne 0) {
    throw "Flet APK build failed with exit code $LASTEXITCODE."
}

Write-Host ""
Write-Host "APK build complete. Check: $ProjectRoot\build\apk"
