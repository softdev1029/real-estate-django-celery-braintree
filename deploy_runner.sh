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
source /var/www/leadsherpa/.env

# pip install -r requirements.txt
echo "Updating environment..."
/home/deploy/.local/bin/pipenv install --ignore-pipfile

# Need to stop uploads before migration and resume them after.
/home/deploy/.local/bin/pipenv run python manage.py stop_uploads
echo "Restarting celery..."
sudo service celery restart
# Only restart celerybeat on runner1 server, there should be only 1 celerybeat running in the cluster
if [ "$HOSTNAME" = runner1 ]; then
    echo "Restarting celerybeat..."
    sudo service celerybeat restart
fi
/home/deploy/.local/bin/pipenv run python manage.py resume_uploads
echo "Setup complete!"