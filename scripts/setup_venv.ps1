$ErrorActionPreference = "Stop"
$Python = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }
& $Python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Write-Host "Virtual environment ready: .venv"
Write-Host "Next: Copy-Item .env.example .env and edit .env"
