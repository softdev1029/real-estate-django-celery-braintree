#!/usr/bin/env bash

# Setup logging file.
dt=$(date '+%Y%m%d%H%M%S');
exec > >(tee -i /tmp/deploy-$dt.log)
exec 2>&1

# Update application code.
cd "$(dirname "$0")"
git reset --hard HEAD
git fetch --tags
git checkout $1

# Load environment variables.
source /var/www/leadsherpa-dev/.env

# pip install -r requirements.txt
pipenv install --ignore-pipfile

# Need to stop uploads before migration and resume them after.
pipenv run python manage.py migrate --no-input
echo "Setup complete restarting uwsgi..."

# Need to stop uploads before migration and resume them after.
pipenv run python manage.py stop_uploads
echo "Restarting celery..."
sudo service celery-dev restart
echo "Restarting celerybeat..."
sudo service celerybeat-dev restart
pipenv run python manage.py resume_uploads

# Restart uwsgi service after everything is ready
sudo service uwsgi-emperor restart
echo "Setup complete!"
