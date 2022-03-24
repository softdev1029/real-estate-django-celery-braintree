#!/usr/bin/env bash

NAME=${1:-"$(git rev-parse --abbrev-ref HEAD)"}
mkdir -p backups/$NAME
docker-compose run -u postgres --rm db pg_dump -h db > backups/$NAME/db.sql
