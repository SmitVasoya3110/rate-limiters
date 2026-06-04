.PHONY: install test run docker-up docker-down clean lint format

install:
	pip install -r requirements.txt

test:
	pytest -v --cov=app --cov-report=html --cov-report=term-missing

test-quick:
	pytest -v

run:
	python -m app.main

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

docker-build:
	docker-compose build

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf .coverage

lint:
	flake8 app tests

format:
	black app tests
	isort app tests

redis-cli:
	redis-cli

redis-flush:
	redis-cli FLUSHALL

help:
	@echo "Available commands:"
	@echo "  install       - Install dependencies"
	@echo "  test          - Run tests with coverage"
	@echo "  test-quick    - Run tests without coverage"
	@echo "  run           - Run the application"
	@echo "  dev           - Run in development mode with auto-reload"
	@echo "  docker-build  - Build Docker images"
	@echo "  docker-up     - Start Docker containers"
	@echo "  docker-down   - Stop Docker containers"
	@echo "  docker-logs   - View Docker logs"
	@echo "  clean         - Clean up generated files"
	@echo "  lint          - Run linter"
	@echo "  format        - Format code"
	@echo "  redis-cli     - Open Redis CLI"
	@echo "  redis-flush   - Flush all Redis data"
