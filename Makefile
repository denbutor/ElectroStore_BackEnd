.PHONY: dev down logs ps seed build

dev:
	docker compose up -d

build:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

ps:
	docker compose ps

seed:
	docker compose exec catalog_service python /scripts/seed.py