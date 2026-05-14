.PHONY: run seed install

install:
	uv sync

run:
	uv run uvicorn src.app:app --reload --port 8000

seed:
	uv run python -m src.db
