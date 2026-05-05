#!/bin/sh

# Wait for the database to be ready before starting Django
if [ "$DATABASE" = "mysql" ]
then
    echo "Waiting for mysql..."

    while ! nc -z $DB_HOST $DB_PORT; do
      sleep 0.1
    done

    echo "MySQL started"
fi

# Run database setup: flush (clean for MVP), migrate, and seed
# python manage.py flush --no-input
if [ "$RUN_MIGRATIONS" = "true" ]; then
    echo "Running migrations..."
    python manage.py migrate
else
    echo "Skipping migrations..."
fi
# python manage.py seed_db

# Hand off execution to the CMD defined in the Dockerfile
exec "$@"
