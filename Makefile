PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
PIP := $(BIN)/pip
PY := $(BIN)/python
MANAGE := $(PY) manage.py
DOCKER ?= docker
COMPOSE ?= $(DOCKER) compose

.PHONY: help venv install migrate makemigrations run superuser shell test check docker-build docker-up docker-down docker-logs

help:
	@echo "Targets:"
	@echo "  make install         Create venv and install dependencies"
	@echo "  make migrate         Apply database migrations"
	@echo "  make makemigrations  Create new migrations"
	@echo "  make run             Run dev server"
	@echo "  make superuser       Create admin user"
	@echo "  make shell           Open Django shell"
	@echo "  make test            Run tests"
	@echo "  make check           Run Django system checks"
	@echo "  make docker-build    Build Docker image"
	@echo "  make docker-up       Start containers"
	@echo "  make docker-down     Stop containers"
	@echo "  make docker-logs     Tail container logs"

$(BIN)/activate:
	$(PYTHON) -m venv $(VENV)

venv: $(BIN)/activate

install: $(BIN)/activate requirements.txt
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

migrate:
	$(MANAGE) migrate

makemigrations:
	$(MANAGE) makemigrations

run:
	$(MANAGE) runserver

superuser:
	$(MANAGE) createsuperuser

shell:
	$(MANAGE) shell

test:
	$(MANAGE) test

check:
	$(MANAGE) check

docker-build:
	$(COMPOSE) build

docker-up:
	$(COMPOSE) up -d

docker-down:
	$(COMPOSE) down

docker-logs:
	$(COMPOSE) logs -f
