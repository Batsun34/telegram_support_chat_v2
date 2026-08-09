#!/usr/bin/env bash
set -euo pipefail
. .venv/bin/activate
alembic upgrade head
exec python -m app.main
