#!/usr/bin/env bash

NAME=${1:-"$(git rev-parse --abbrev-ref HEAD)"}
mkdir -p backups/$NAME
docker-compose run --rm web pipenv run ./manage.py reset_db --noinput
docker-compose run -u postgres --rm db psql -h db < backups/$NAME/db.sql
