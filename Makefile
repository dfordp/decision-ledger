.PHONY: help build up down logs seed verify clean test

help:
    @echo "DecisionLedger - Docker Commands"
    @echo "================================"
    @echo "make build      - Build Docker images"
    @echo "make up         - Start all services"
    @echo "make down       - Stop all services"
    @echo "make logs       - View logs"
    @echo "make seed       - Run seed script"
    @echo "make verify     - Verify seed data"
    @echo "make clean      - Remove all containers and volumes"
    @echo "make test       - Run tests"
    @echo "make restart    - Restart all services"

build:
    docker-compose build

up:
    docker-compose up -d
    @echo "Waiting for services to be ready..."
    @sleep 5
    @echo "✓ Services started"
    @echo "Backend: http://localhost:8000"
    @echo "Database: localhost:5432"

down:
    docker-compose down

logs:
    docker-compose logs -f

logs-backend:
    docker-compose logs -f backend

logs-db:
    docker-compose logs -f postgres

seed:
    @echo "Running seed script..."
    docker-compose --profile seed up seeder
    @echo "✓ Seeding complete"

verify:
    @echo "Verifying seed data..."
    docker-compose exec backend python scripts/verify_seed.py

clean:
    docker-compose down -v
    docker system prune -f

restart:
    docker-compose restart

test-connection:
    docker-compose exec backend python scripts/test_connection.py

test-embeddings:
    docker-compose exec backend python scripts/test_embeddings.py

shell-backend:
    docker-compose exec backend bash

shell-db:
    docker-compose exec postgres psql -U postgres -d decisionledger

reset: down clean build up seed
    @echo "✓ Complete reset done"