.PHONY: help up down logs test test-api test-web lint migrate prod-config

help:            ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

up:              ## Start the local dev stack
	docker compose up --build -d

down:            ## Stop the local dev stack
	docker compose down

logs:            ## Tail dev stack logs
	docker compose logs -f --tail=100

test: test-api test-web  ## Run all tests

test-api:        ## API + infrastructure tests (starts throwaway Postgres/Redis)
	scripts/test-services.sh up
	cd apps/api && REDIS_URL=redis://localhost:6379/15 uv run pytest -q tests ../../tests/infrastructure

test-web:        ## Web unit/component tests
	npm test

lint:            ## Lint and type-check everything
	cd apps/api && uv run ruff check . && uv run ruff format --check . && uv run mypy app
	npm run lint && npm run typecheck

migrate:         ## Apply migrations in the dev stack
	docker compose run --rm migrate

prod-config:     ## Validate production compose with .env
	docker compose -f docker-compose.prod.yml --env-file .env config -q
