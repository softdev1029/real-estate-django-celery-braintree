FROM python:3.6.13-buster
ENV PYTHONUNBUFFERED 1

# globally disable caching pip packages (counter-intuitive but correct)
ENV PIP_NO_CACHE_DIR false

# keep logs clean
ENV PIPENV_NOSPIN 1

# needed by pipenv to activate shell
ENV SHELL /bin/bash

# provide a home directory that is safe for a non-root user
ENV HOME=/tmp/home

ARG WORKDIR=/app
WORKDIR $WORKDIR

RUN set -eux \
    # make a home directory safe for non-root user
    && mkdir -p $HOME \
    # update os packages
    && apt update -y \
    # install and upgrade pip and pipenv
    && pip install --upgrade pip pipenv

# copy the Pipfiles in
COPY Pipfile Pipfile.lock $WORKDIR/

RUN set -eux \
    # install app python deploy dependencies
    && pipenv install --deploy

RUN set -eux \
    #  install os dev dependencies
    && apt install -y \
        # graphviz for model graphs
        graphviz graphviz-dev \
        # provide postgres client for dbshell
        postgresql-client \
        # editor for git
        vim

RUN set -eux \
    #  install app python dev dependencies
    && pipenv sync --dev \
    # do this after all things "installed" by root
    # not worried about work dir because bind mounting will address that
    && chmod -R a+w $HOME

# celery worker specific
ENV C_FORCE_ROOT=1

# run all commands in pipenv context
ENTRYPOINT [ "pipenv", "run" ]

# Dev image will not have source code inside... it will always be bind-mounted
# copy the app code in after environment prep to avoid cache-busting
# COPY . $WORKDIR/
