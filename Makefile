# editorial.workflow — run `make` to list targets. Logic lives in bin/, this is the menu.
SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help
s ?=

.PHONY: help up start down down-all restart setup dev check check-live token url logs ps build \
        scribus service-start service-stop service-install service-enable service-uninstall \
        service-status service-logs designcraft-start designcraft-stop designcraft-install \
        designcraft-uninstall designcraft-status designcraft-logs designcraft-audit \
        rotate test lint fmt lock clean

help: ## Show this help
	@awk 'BEGIN{FS=":.*## "} /^[a-z-]+:.*## /{printf "  \033[36m%-17s\033[0m %s\n",$$1,$$2}' $(MAKEFILE_LIST)

up: ## ONE COMMAND: setup, check, start (scribus-mcp service in host mode) and print URL + token
	@bin/up

start: ## Start without rebuilding images
	@bin/up --no-build

down: ## Stop the stack (+ the transient scribus-mcp service started by `make up`)
	@bin/down

down-all: ## Stop the stack and also an installed scribus-mcp service
	@bin/down --all

restart: down up ## Recreate the stack

setup: ## Create .env with generated secrets and the editorial folder
	@bin/setup

dev: ## Setup + local .venv for development and tests
	@bin/setup --dev

check: ## Preflight checks (tools, .env, folder, host prerequisites, ports, compose)
	@bin/check

check-live: ## End-to-end checks against the running stack (local, policy, ngrok, bridge)
	@bin/check --live

token: ## Mint an OAuth access token and print client snippets
	@bin/token

url: ## Print the public MCP URL
	@bin/url

logs: ## Follow logs (make logs s=gateway|scribus-mcp|ngrok)
	@bin/compose logs -f --tail=100 $(s)

ps: ## Show containers
	@bin/compose ps

build: ## Build images
	@bin/compose build

scribus: ## Host mode: open your Scribus with the MCP bridge loaded
	@bin/scribus

service-start: ## Host mode: run scribus-mcp now as a transient systemd unit
	@bin/host-service start

service-stop: ## Host mode: stop the scribus-mcp unit
	@bin/host-service stop

service-install: ## Host mode: install the scribus-mcp unit (persistent, not at login)
	@bin/host-service install

service-enable: ## Host mode: install and start the scribus-mcp unit at every login
	@bin/host-service install --enable

service-uninstall: ## Host mode: remove unit + runtime venv (leaves nothing behind)
	@bin/host-service uninstall

service-status: ## Host mode: unit, runtime, endpoint and bridge status
	@bin/host-service status

service-logs: ## Host mode: follow scribus-mcp logs (journald)
	@bin/host-service logs

designcraft-start: ## DesignCraft connector: run mcp-proxy + headless DesignCraft as a transient unit
	@bin/designcraft-service start

designcraft-stop: ## DesignCraft connector: stop its unit
	@bin/designcraft-service stop

designcraft-install: ## DesignCraft connector: install its unit (persistent, not at login)
	@bin/designcraft-service install

designcraft-uninstall: ## DesignCraft connector: remove unit + runtime (leaves nothing behind)
	@bin/designcraft-service uninstall

designcraft-status: ## DesignCraft connector: unit, runtime, versions and endpoint
	@bin/designcraft-service status

designcraft-logs: ## DesignCraft connector: follow logs (journald)
	@bin/designcraft-service logs

designcraft-audit: ## After a DesignCraft upgrade: what changed since the reviewed version
	@bin/designcraft-audit

rotate: ## Rotate GATEWAY_SECRET (revokes every token and client)
	@bin/rotate

test: ## Lint + unit tests (+ shellcheck if installed)
	@bin/test

lint: ## Ruff lint only
	@.venv/bin/ruff check src tests

fmt: ## Format Python code
	@.venv/bin/ruff format src tests && .venv/bin/ruff check --fix src tests

lock: ## Pin dependencies with hashes (uv.lock + containers/*/requirements.txt); run after changing pyproject, SCRIBUS_MCP_VERSION or MCP_PROXY_VERSION
	@bin/lock

clean: ## Remove local caches (keeps .env and your editorial folder)
	@rm -rf .venv .pytest_cache .ruff_cache .coverage build dist src/*.egg-info
	@find . -name __pycache__ -type d -prune -exec rm -rf {} +
