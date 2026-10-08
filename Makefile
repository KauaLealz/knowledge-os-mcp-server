.PHONY: help install dev test test-cov lint format typecheck run ui clean

help:
	@echo "MCP Knowledge OS - Targets disponíveis:"
	@echo "  make install      - Instala dependências"
	@echo "  make dev          - Instala com extras de dev (pytest, etc)"
	@echo "  make test         - Roda testes pytest"
	@echo "  make test-cov     - Testes com cobertura"
	@echo "  make lint         - Lint com ruff"
	@echo "  make format       - Formata código com black"
	@echo "  make typecheck    - Verifica tipos com mypy"
	@echo "  make run          - Inicia servidor MCP (stdio)"
	@echo "  make ui           - Sobe a UI web local (127.0.0.1)"
	@echo "  make clean        - Remove artifacts, cache, etc"

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

run:
	knowledge-mcp

ui:
	knowledge-mcp ui

test:
	pytest -v

test-cov:
	pytest -v --cov=knowledge_os --cov-report=html

lint:
	ruff check src/ tests/

format:
	black src/ tests/
	ruff check --fix src/ tests/

typecheck:
	mypy src/knowledge_os/

clean:
	rm -rf build/ dist/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .coverage -exec rm -rf {} +
	find . -type d -name htmlcov -exec rm -rf {} +

.DEFAULT_GOAL := help
