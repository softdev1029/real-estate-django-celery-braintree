## Summary
It is a tool to generate and manage leads for real estate investors.

## Installation
The only system requirements are [git](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git), [docker](https://docs.docker.com/install/) and [docker-compose](https://docs.docker.com/compose/install/), everything else is handled by docker.

```bash
cd lead-sherpa
cp template.env .env  # populate with real values
# add CONTAINER_UID to .env to match container to host permissions
echo "CONTAINER_UID=$UID" >> .env
docker-compose up -d
# for Windows users - change EOL to LF in manage.py to prevent bash script error
make loaddata
```

***Pro-tip:*** Remember that if you change your `.env` file you will need to re-*create* your containers.  `docker-compose up -d` will detect this condition and do you the favor of forcibly re-creating containers if you run it again after making changes to `.env`.

## Deployment
We have a multi-server environment deployed to linode. Below are some of the characteristics of our server setup.

- uwsgi/nginx for each web server
- celery worker on each server
- redis server on each server

CircleCI handles deployment when pushing to develop, staging or master branches, deploying to the respective server or server groups through the `deploy.sh` script.

#### SSH access
You should have ssh access, which is granted through the linode team. There are a couple quick commands to ssh into the servers (in makefile), given that your local user is the same username as on the servers. If not, you can ssh with ssh {username}@{server_id}.

#### Celery
Each of our servers is running a celery worker to handle queued tasks that are sent to the central redis server.

`sudo service celery status` - View data about service including  latest log, command and where the execution code is located.

#### Scheduled tasks
Scheduled tasks are currently handled by cron jobs by the root user on our servers. We only run each cron job on a single server and separate those jobs to different servers. You can modify the cron jobs by switching to the root user and running `crontab -e`.

#### Running manage commands
The application is located at `/var/www/`. Inside this folder you'll find our django application and can activate the environment with `pipenv shell` (or other standard pipenv commands). From there you can run management commands such as `./manage.py shell`. Be careful when in production!



## Usage

#### Seed data
You can get up and running with data by running `make loaddata`. When we need to update seed data we should reset to the original loaddata update the data and then run `make dumpdata`. Data should be kept to a minimum while being able to provide a real experience with test data.

#### Seed accounts

You can view the [full set of accounts](https://github.com/lead-sherpa/wiki/Test-Accounts) in the seed data, or quickly get into the system using *admin//sherp456* as a sherpa admin user or *george@asdf.com//testu123* as the main account user that fulfills most situations.

#### Creating new users

Other than the test users, you can also create new users.

1) By default in the seed data, you can sign up with the invitation codes choice, 500 or 1000.

2) You'll need to verify your account, which you can find the link in your terminal.

3) You'll want to create a subscription, which can be done with a [braintree test card](https://developers.braintreepayments.com/reference/general/testing/ruby#valid-card-numbers)

#### Receiving test messages
We can fake receiving messages by using a management command. This does not actually go through the webhook process, but just fakes the data.

`./manage.py receive_message <prospect_id> <message>`

#### Receiving webhooks
With telnyx we can setup [ngrok](https://ngrok.com/) to receive the webhooks from messages sent from local server.

1) Refer to telnyx [ngrok setup docs](https://developers.telnyx.com/docs/v2/development/ngrok)
2) Once ngrok is running, add the url to local .env file `NGROK_URL=<ngrok_id>.ngrok.io`
3) You should now be receiving the webhook requests

#### Sending and receiving real messages

Sometimes it's beneficial to test sending/receiving real messages, to do this there are a few steps involved. This is always going to be a temporary configuration, because the ngrok url will be changing for each developer and also will change each time you restart your ngrok server.

1) First you'll need to install and run [ngrok](https://ngrok.com/).
2) Once ngrok is running, add the url to local .env file `NGROK_URL=<ngrok_id>.ngrok.io` (without protocol), which allows your server to receive the webhook requests from telnyx. Make sure to restart your docker container after making this change.
3) Then you'll need to update George's Seattle/Tac market's [messaging profile](https://portal.telnyx.com/#/app/messaging/edit/4f3e5bb0-2619-4812-81ec-1d6968cb1de5) and the [dev relay profile](https://portal.telnyx.com/#/app/messaging/edit/37bc298e-6a06-4472-af3e-8b80d31c2379) (if using relay locally) to be the ngrok url. You can use a shortcut by running `./manage.py setup_george_relay http://<id>.ngrok.io`.
4) The last step is that in your `core/settings/local_user.py` file (ignored/private, might need to add) you'll need to add `USE_TEST_MESSAGING = False` to turn on real messaging. Make sure to turn that off when done!
5) Now you're all set to send live messgaes from George's Seattle/Tac market numbers and receive incoming messages as well.

#### Setting a delay for API requests
To have a more realistic frontend development experience, we can delay the api requests served by the server. In the `.env` file you can set a `REQUEST_TIME_DELAY` to a given number of seconds, or partial seconds such as `1` or `0.5`.
