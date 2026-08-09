.PHONY: install migrate run test lint

install:
	python -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -r requirements-dev.txt

migrate:
	.venv/bin/alembic upgrade head

run:
	.venv/bin/python -m app.main

test:
	.venv/bin/pytest -q

lint:
	.venv/bin/ruff check .
