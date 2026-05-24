param(
    [switch]$SkipDocker,
    [switch]$StartBackend,
    [switch]$StartFrontend
)

$ErrorActionPreference = 'Stop'

function Write-Step {
    param([string]$Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Assert-Command {
    param(
        [string]$Name,
        [string]$InstallHint
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $Name. $InstallHint"
    }
}

function New-CameraCredentialKey {
    Add-Type -AssemblyName System.Security
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [Convert]::ToBase64String($bytes).Replace('+', '-').Replace('/', '_')
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendPath = Join-Path $repoRoot 'backend'
$frontendPath = Join-Path $repoRoot 'parking_web'
$venvPython = Join-Path $backendPath 'venv\Scripts\python.exe'
$envFile = Join-Path $backendPath '.env'

Write-Step 'Checking required tools'
Assert-Command -Name 'python' -InstallHint 'Install Python 3.10+ and add it to PATH.'
Assert-Command -Name 'flutter' -InstallHint 'Install Flutter SDK and ensure flutter doctor passes.'
if (-not $SkipDocker) {
    Assert-Command -Name 'docker' -InstallHint 'Install Docker Desktop and make sure it is running.'
}

Write-Step 'Preparing backend virtual environment'
if (-not (Test-Path $venvPython)) {
    Push-Location $backendPath
    python -m venv venv
    Pop-Location
}

Write-Step 'Installing backend dependencies'
Push-Location $backendPath
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt
Pop-Location

Write-Step 'Creating backend .env if missing'
if (-not (Test-Path $envFile)) {
    $cameraKey = New-CameraCredentialKey
    @(
        '# Auto-generated for local development on first setup',
        'DATABASE_URL=postgresql://postgres:1234@localhost:5432/parking_db',
        "CAMERA_CREDENTIAL_KEY=$cameraKey"
    ) | Set-Content -Path $envFile -Encoding UTF8
    Write-Host "Created $envFile"
} else {
    Write-Host "$envFile already exists. Keeping existing values."
}

if (-not $SkipDocker) {
    Write-Step 'Starting database with Docker Compose'
    Push-Location $repoRoot
    docker compose up -d database
    Pop-Location
}

Write-Step 'Installing Flutter dependencies'
Push-Location $frontendPath
flutter pub get
Pop-Location

Write-Step 'Setup completed'
Write-Host 'Next commands:' -ForegroundColor Green
Write-Host "1) Backend:  Set-Location $backendPath ; .\\venv\\Scripts\\python.exe main.py"
Write-Host "2) Frontend: Set-Location $frontendPath ; flutter run -d chrome"

if ($StartBackend) {
    Write-Step 'Starting backend now'
    Push-Location $backendPath
    & $venvPython main.py
    Pop-Location
}

if ($StartFrontend) {
    Write-Step 'Starting frontend now'
    Push-Location $frontendPath
    flutter run -d chrome
    Pop-Location
}
