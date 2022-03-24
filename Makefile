### Operational commands ###

# When django-admin creates files (makemigrations, startapp, etc) we need to own
# the files to modify them.
chown:
	sudo chown -R ${USER}:${USER} .

# Sometimes when switching branches the pyc cache will crash your server
clear-cache:
	find . -name "*.pyc" -exec rm -f {} \;


### Django commands ###
# Shortcuts to run common django commands in our docker containerr
migrate:
	docker-compose run --rm web ./manage.py migrate

makemigrations:
	docker-compose run --rm web ./manage.py makemigrations

checkmigrations:
	docker-compose run --rm web ./manage.py makemigrations --check --dry-run

test: checkmigrations
	docker-compose run --rm web ./manage.py test --noinput $(test_params)

coverage:
	docker-compose run --rm web coverage run --omit='.venv/*','*/migrations/*.py','*/admin.py' manage.py test --noinput

shell:
	docker-compose run --rm web ./manage.py shell

loaddata: migrate
	docker-compose run --rm web ./manage.py flush --noinput
	docker-compose run --rm web ./manage.py loaddata sherpa/data/seed.json
	docker-compose run --rm web ./manage.py post_load_data

dumpdata:
	docker-compose run --rm web ./manage.py dumpdata --exclude=contenttypes --exclude=auth.Permission --output sherpa/data/seed.json

### Service Commands ###
reset-db:
	docker-compose stop
	docker-compose run --rm web ./manage.py reset_db --noinput
	make up

up:
	docker-compose up -d
	make loaddata
	make stacker

restart-celery:
	docker-compose restart celery

### Linting ###
flake:
	docker-compose run --rm web python -m flake8

### Search ###
stacker:
	docker-compose run --rm web ./manage.py delete_stacker_indexes
	docker-compose run --rm web ./manage.py build_stacker_indexes
	docker-compose run --rm web ./manage.py populate_stacker_indexes

### DevOps commands ###

# Shortcuts to ssh into the servers if your username matches
ssh-prod:
	ssh ${USER}@104.237.141.168
ssh-staging:
	ssh ${USER}@45.79.29.235
ssh-develop:
	ssh ${USER}@45.33.26.96
ssh-db:
	ssh ${USER}@45.33.117.96
