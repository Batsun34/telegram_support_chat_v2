$ErrorActionPreference = "Stop"
& .\.venv\Scripts\alembic.exe upgrade head
& .\.venv\Scripts\python.exe -m app.main
