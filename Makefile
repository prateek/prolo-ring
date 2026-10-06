.PHONY: check fmt test install-local

check:
	uv run ruff format --check .
	uv run ruff check .
	uv run pyright
	uv run pytest -q

fmt:
	uv run ruff format .
	uv run ruff check --fix .

test:
	uv run pytest -q

install-local:
	uv tool install --force --editable .
