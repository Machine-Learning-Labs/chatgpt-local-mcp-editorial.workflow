#!/usr/bin/env bash
# Shared helpers for bin/* scripts. Source it, don't run it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
cd "$ROOT"

# shellcheck disable=SC2034  # colors are used by the scripts that source this file
if [[ -t 1 ]]; then
  C_RED=$'\e[31m' C_GRN=$'\e[32m' C_YLW=$'\e[33m' C_BLU=$'\e[34m' C_DIM=$'\e[2m' C_OFF=$'\e[0m'
else
  C_RED='' C_GRN='' C_YLW='' C_BLU='' C_DIM='' C_OFF=''
fi

info() { printf '%s==>%s %s\n' "$C_BLU" "$C_OFF" "$*"; }
ok()   { printf '%s ok %s %s\n' "$C_GRN" "$C_OFF" "$*"; }
warn() { printf '%swarn%s %s\n' "$C_YLW" "$C_OFF" "$*" >&2; }
fail() { printf '%sfail%s %s\n' "$C_RED" "$C_OFF" "$*" >&2; }
die()  { fail "$*"; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# Read KEY from .env without sourcing it (values may contain spaces or symbols).
env_get() {
  local key="$1" default="${2:-}" line
  if [[ -f "$ENV_FILE" ]] && line=$(grep -E "^${key}=" "$ENV_FILE" | tail -n1); then
    line="${line#*=}"; line="${line%\"}"; line="${line#\"}"
    printf '%s' "${line:-$default}"
  else
    printf '%s' "$default"
  fi
}

# Set KEY=VALUE in .env (replace or append).
env_set() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp)"
  if grep -qE "^${key}=" "$ENV_FILE" 2>/dev/null; then
    awk -v k="$key" -v v="$value" 'BEGIN{FS=OFS="="} $1==k{print k "=" v; next} {print}' \
      "$ENV_FILE" >"$tmp"
  else
    cat "$ENV_FILE" >"$tmp" 2>/dev/null || true
    printf '%s=%s\n' "$key" "$value" >>"$tmp"
  fi
  mv "$tmp" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
}

# uv is a standalone binary: using the copy that lives inside a conda env does NOT
# activate or touch that env. Order: $UV / .env UV, PATH, standalone installs, conda envs.
find_uv() {
  local candidate
  for candidate in "${UV:-}" "$(env_get UV)" "$(command -v uv 2>/dev/null || true)" \
    "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    [[ -n "$candidate" && -x "$candidate" ]] && { echo "$candidate"; return 0; }
  done
  for candidate in "$HOME"/{miniconda3,anaconda3,miniforge3,mambaforge}/{bin,envs/*/bin}/uv; do
    [[ -x "$candidate" ]] && { echo "$candidate"; return 0; }
  done
  return 1
}

random_secret() {
  if have openssl; then openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-"${1:-48}"
  else head -c 64 /dev/urandom | base64 | tr -d '\n/+=' | cut -c1-"${1:-48}"; fi
}

# Detect the compose implementation: $COMPOSE, docker compose, podman compose, podman-compose.
compose_cmd() {
  local override="${COMPOSE:-$(env_get COMPOSE)}"
  if [[ -n "$override" ]]; then echo "$override"; return; fi
  if have docker && docker compose version >/dev/null 2>&1; then echo "docker compose"; return; fi
  if have podman-compose; then echo "podman-compose"; return; fi
  if have podman && podman compose version >/dev/null 2>&1; then echo "podman compose"; return; fi
  return 1
}

engine() {
  case "$(compose_cmd 2>/dev/null || true)" in
    docker*) echo docker ;;
    podman*) echo podman ;;
    *) have docker && echo docker || { have podman && echo podman; } || echo none ;;
  esac
}

# Compose files and profile depend on MCP_MODE:
#   container → docker-compose.yml + profile "container" (scribus-mcp in the stack)
#   host      → docker-compose.yml + docker-compose.host.yml (scribus-mcp = systemd user service)
compose_env() {
  export PODMAN_COMPOSE_WARNING_LOGS=false
  COMPOSE_ARGS=(-f "$ROOT/docker-compose.yml")
  if [[ "$(env_get MCP_MODE container)" == "host" ]]; then
    COMPOSE_ARGS+=(-f "$ROOT/docker-compose.host.yml")
  else
    COMPOSE_ARGS+=(--profile container)
  fi
}

mcp_mode() { env_get MCP_MODE container; }
editorial_root() { env_get EDITORIAL_ROOT "$HOME/Editorial"; }

# Container user so files in EDITORIAL_ROOT end up owned by you:
# rootless podman maps container root to your user; docker needs your uid:gid.
container_user() {
  if [[ "$(engine)" == "podman" ]] && [[ "$(podman info --format '{{.Host.Security.Rootless}}' 2>/dev/null)" == "true" ]]; then
    echo "0:0"
  else
    echo "$(id -u):$(id -g)"
  fi
}

compose() {
  local cmd
  cmd="$(compose_cmd)" || die "no compose found: install docker compose or podman-compose"
  compose_env
  CONTAINER_USER="${CONTAINER_USER:-$(container_user)}"
  export CONTAINER_USER
  # shellcheck disable=SC2086
  $cmd --env-file "$ENV_FILE" "${COMPOSE_ARGS[@]}" "$@"
}

gateway_local_url() { echo "http://127.0.0.1:$(env_get GATEWAY_PORT 8080)"; }

# Public URL: NGROK_DOMAIN, else the ngrok inspection API, else the ngrok logs.
public_url() {
  local domain url
  domain="$(env_get NGROK_DOMAIN)"
  if [[ -n "$domain" ]]; then echo "https://${domain#https://}"; return; fi
  url="$(curl -fsS "http://127.0.0.1:$(env_get NGROK_INSPECT_PORT 4040)/api/tunnels" 2>/dev/null \
    | grep -oE '"public_url":"https://[^"]+"' | head -n1 | cut -d'"' -f4 || true)"
  if [[ -z "$url" ]]; then
    url="$(compose logs ngrok 2>/dev/null | grep -oE 'url=https://[^ ]+' | tail -n1 | cut -d= -f2 || true)"
  fi
  [[ -n "$url" ]] && echo "$url"
}

wait_for() {
  local what="$1" timeout="$2"; shift 2
  local start=$SECONDS
  until "$@" >/dev/null 2>&1; do
    (( SECONDS - start >= timeout )) && return 1
    sleep 1
  done
  ok "$what"
}
