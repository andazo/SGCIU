SHELL := /bin/sh

.PHONY: bootstrap up down logs status smoke verify test e2e build cost-report monitoring-setup cloud-build-setup

bootstrap:
	@if [ ! -f .env ]; then cp .env.example .env; fi
	@echo "Configuracion preparada en .env. Defina OPENAI_API_KEY antes de usar los modulos de IA."

up:
	@test -f .env || (echo "Falta .env. Ejecute 'make bootstrap' primero." && exit 1)
	@grep -Eq '^OPENAI_API_KEY=.+$$' .env || (echo "Falta OPENAI_API_KEY en .env." && exit 1)
	docker compose up --build --detach --wait
	@echo "SGCIU disponible en http://localhost:5173 (API: http://localhost:8000/docs)."

down:
	docker compose down

logs:
	docker compose logs --follow --tail=200

status:
	docker compose ps

smoke:
	curl --fail --silent --show-error http://localhost:8000/health
	curl --fail --silent --show-error http://localhost:8000/ready
	curl --fail --silent --show-error http://localhost:5173/ >/dev/null

verify:
	cd backend && .venv/bin/ruff check app tests migrations
	cd backend && .venv/bin/pytest --cov=app --cov-report=term-missing --cov-fail-under=70
	cd frontend && npm ci && npm run build
	docker compose config --quiet

test:
	cd backend && .venv/bin/pytest -m "not e2e"

e2e:
	cd backend && .venv/bin/pytest -m e2e -v

build:
	docker compose build

cost-report:
	cd backend && PYTHONPATH=. .venv/bin/python -m app.evaluation.cost_report --check

monitoring-setup:
	./infra/monitoring/setup.sh tfm-sgciu us-central1

cloud-build-setup:
	./infra/iam/setup-cloud-build.sh tfm-sgciu us-central1
