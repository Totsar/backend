PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
PIP := $(BIN)/pip
PY := $(BIN)/python
MANAGE := $(PY) manage.py

.PHONY: help venv install migrate makemigrations run superuser shell test check

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
