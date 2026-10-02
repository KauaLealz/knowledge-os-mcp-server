.PHONY: help install dev test lint format bootstrap check-db run clean

help:
	@echo "MCP Knowledge OS - Targets disponíveis:"
	@echo "  make install      - Instala dependências"
	@echo "  make dev          - Instala com extras de dev (pytest, etc)"
	@echo "  make bootstrap    - Cria banco de dados e labels padrão"
	@echo "  make check-db     - Verifica conexão com banco"
	@echo "  make test         - Roda testes pytest"
	@echo "  make test-cov     - Testes com cobertura"
	@echo "  make lint         - Lint com ruff"
	@echo "  make format       - Formata código com black"
	@echo "  make typecheck    - Verifica tipos com mypy"
	@echo "  make run          - Inicia servidor MCP"
	@echo "  make clean        - Remove artifacts, cache, etc"

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

bootstrap:
	python src/main.py --bootstrap

check-db:
	python src/main.py --check-db

run:
	python src/main.py

test:
	pytest -v

test-cov:
	pytest -v --cov=src --cov-report=html

lint:
	ruff check src/ tests/

format:
	black src/ tests/
	ruff check --fix src/ tests/

typecheck:
	mypy src/

clean:
	rm -rf build/ dist/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .coverage -exec rm -rf {} +
	find . -type d -name htmlcov -exec rm -rf {} +

.DEFAULT_GOAL := help
