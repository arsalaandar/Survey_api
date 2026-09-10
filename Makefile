.PHONY: migrate test lint
migrate:
	alembic upgrade head
test:
	pytest --cov=app
lint:
	ruff check app tests
