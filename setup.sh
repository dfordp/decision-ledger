#!/bin/bash
set -e

echo "Waiting for PostgreSQL to be ready..."
until PGPASSWORD=$POSTGRES_PASSWORD psql -h "postgres" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '\q'; do
  >&2 echo "Postgres is unavailable - sleeping"
  sleep 1
done

>&2 echo "Postgres is up - executing command"

# Run migrations or seeding if needed
if [ "$RUN_SEED" = "true" ]; then
  echo "Running seed script..."
  python scripts/seed_data.py
fi

# Execute the main command
exec "$@"