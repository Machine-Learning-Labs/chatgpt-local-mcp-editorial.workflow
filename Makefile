# editorial.workflow — run `make` to list targets. Logic lives in bin/, this is the menu.
SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help
s ?=

.PHONY: help up start down restart setup dev check check-live token url logs ps build \
        host-mcp rotate test lint fmt clean

help: ## Show this help
	@awk 'BEGIN{FS=":.*## "} /^[a-z-]+:.*## /{printf "  \033[36m%-11s\033[0m %s\n",$$1,$$2}' $(MAKEFILE_LIST)

up: ## ONE COMMAND: setup, check, build, start and print public URL + OAuth token
	@bin/up

start: ## Start without rebuilding images
	@bin/up --no-build

down: ## Stop and remove the stack
	@bin/compose down --remove-orphans

restart: down up ## Recreate the stack

setup: ## Create .env with generated secrets (imports ngrok authtoken)
	@bin/setup

dev: ## Setup + local .venv for development and tests
	@bin/setup --dev

check: ## Preflight checks (tools, .env, ports, compose file)
	@bin/check

check-live: ## End-to-end checks against the running stack (local + ngrok)
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

host-mcp: ## Host mode: run scribus-mcp on this machine (uses your local Scribus)
	@bin/host-mcp

rotate: ## Rotate GATEWAY_SECRET (revokes every token and client)
	@bin/rotate

test: ## Lint + unit tests (+ shellcheck if installed)
	@bin/test

lint: ## Ruff lint only
	@.venv/bin/ruff check src tests

fmt: ## Format Python code
	@.venv/bin/ruff format src tests && .venv/bin/ruff check --fix src tests

clean: ## Remove local caches (keeps .env and workspace/)
	@rm -rf .venv .pytest_cache .ruff_cache .coverage build dist src/*.egg-info
	@find . -name __pycache__ -type d -prune -exec rm -rf {} +
