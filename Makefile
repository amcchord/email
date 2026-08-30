SHELL := /bin/bash
TEST_DATABASE_URL ?= postgresql+asyncpg://mailtest:mailtest@127.0.0.1:1/mailtest

.PHONY: setup test frontend-test frontend-build check remote-status progress

setup:
	./scripts/workspace/bootstrap.sh

test:
	@test -x .venv/bin/python || (echo "Run 'make setup' first." >&2; exit 1)
	DATABASE_URL="$(TEST_DATABASE_URL)" .venv/bin/python -m pytest backend/tests

frontend-test:
	@test -d frontend/node_modules || (echo "Run 'make setup' first." >&2; exit 1)
	npm --prefix frontend test

frontend-build:
	@test -d frontend/node_modules || (echo "Run 'make setup' first." >&2; exit 1)
	npm --prefix frontend run build

check: test frontend-test frontend-build

remote-status:
	./scripts/ops/remote-status.sh

progress:
	@sed -n '1,220p' docs/progress/CURRENT.md
