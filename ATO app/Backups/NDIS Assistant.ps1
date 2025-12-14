# NDIS Assistant.ps1 - FIXED
# Place in: C:\Users\alles\My Drive\ATO app\

$ErrorActionPreference = "Stop"

# --- CONFIGURATION (NO SPACES IN VARIABLES) ---
$PYTHON_EXE = "C:\Users\alles\AppData\Local\Programs\Python\Python314\python.exe"
$APP_SCRIPT = "C:\Users\alles\My Drive\ATO app\app.py"
$ROOT_DIR = "C:\Users\alles\My Drive\ATO app"

# --- VALIDATION ---
if (-not (Test-Path $PYTHON_EXE)) {
    throw "Python not found at: $PYTHON_EXE"
}
if (-not (Test-Path $APP_SCRIPT)) {
    throw "app.py not found at: $APP_SCRIPT"
}

# --- LAUNCH (CORRECTLY QUOTED) ---
Set-Location -Path $ROOT_DIR

# Use Start-Process with proper argument quoting
Start-Process -FilePath $PYTHON_EXE -ArgumentList "`"$APP_SCRIPT`"" -Wait -NoNewWindow