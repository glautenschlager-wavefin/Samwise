.PHONY: help install format lint lint-fix type-check test all-checks clean ext-install ext-build ext-watch serve

help:
	@echo "Samwise Development Commands"
	@echo "============================="
	@echo "make install         Install dependencies"
	@echo "make format          Format code (black + isort)"
	@echo "make lint            Run linters (ruff)"
	@echo "make lint-fix        Auto-fix lint issues with ruff"
	@echo "make type-check      Run type checker (mypy)"
	@echo "make test            Run tests (pytest)"
	@echo "make all-checks      Run all checks (format, lint, type-check, test)"
	@echo "make clean           Remove cache and temporary files"
	@echo ""
	@echo "Extension Commands"
	@echo "=================="
	@echo "make ext-install     Install extension dependencies"
	@echo "make ext-build       Build extension"
	@echo "make ext-watch       Watch extension for changes"
	@echo ""
	@echo "Server Commands"
	@echo "==============="
	@echo "make serve           Start the Samwise backend server"

install:
	poetry install

format:
	poetry run black src/ tests/
	poetry run isort src/ tests/

lint:
	poetry run ruff check src/ tests/

lint-fix:
	poetry run ruff check --fix src/ tests/

type-check:
	poetry run mypy src/

test:
	poetry run pytest tests/ -v

all-checks: format lint type-check test

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf build dist

# --- Extension (VS Code) ---
ext-install:
	cd extension && npm install

ext-build:
	cd extension && npm run compile

ext-watch:
	cd extension && npm run watch

serve:
	poetry run samwise

.DEFAULT_GOAL := help
