#!/usr/bin/env bash
# Brings the Compose install up from this checkout and checks that it works; CI runs it.
#   deploy/compose/smoke-test.sh          the plain install on PENARIA_PORT (18080 by default)
#   deploy/compose/smoke-test.sh --https  then also the HTTPS overlay, on ports 80 and 443
# It uses a Compose project of its own, so an install on this machine is left alone.
set -euo pipefail
cd "$(dirname "$0")"

port=${PENARIA_PORT:-18080}
env_file=$(mktemp)
project=(docker compose --project-name penaria-smoke-test --env-file "$env_file" -f compose.yaml -f compose.build.yaml)

cleanup() {
    status=$?
    if [ "$status" -ne 0 ]; then
        "${project[@]}" -f compose.https.yaml logs --no-color --tail 200 || true
    fi
    "${project[@]}" -f compose.https.yaml down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -f "$env_file"
    exit "$status"
}
trap cleanup EXIT

# Made once: the database keeps the password it was created with.
secret_key=$(openssl rand -hex 32)
postgres_password=$(openssl rand -hex 24)

write_env() {
    cat > "$env_file" <<ENV
PENARIA_PUBLIC_URL=$1
PENARIA_SECRET_KEY=$secret_key
POSTGRES_PASSWORD=$postgres_password
PENARIA_PORT=$port
PENARIA_DOMAIN=localhost
ENV
}

# The app answers, a client-side route falls back to it, and /api reaches the server.
check() {
    base=$1
    shift
    curl --fail --silent --show-error "$@" --output /dev/null "$base/"
    curl --fail --silent --show-error "$@" --output /dev/null "$base/homes/new"
    curl --fail --silent --show-error "$@" "$base/api/v1/setup" | grep --quiet '"needed"'
}

echo "== the plain install"
write_env "http://localhost:$port"
"${project[@]}" up --detach --build --wait
check "http://localhost:$port"
# The setup screen tells people to find the token exactly like this.
"${project[@]}" logs penaria-server | grep --quiet "setup token"
"${project[@]}" exec -T penaria-server python -m penaria.apps.cli --help >/dev/null

if [ "${1:-}" = "--https" ]; then
    echo "== the HTTPS overlay"
    write_env "https://localhost"
    "${project[@]}" -f compose.https.yaml up --detach --wait
    # Caddy signs "localhost" with its own authority, hence --insecure; a moment for it to start.
    for _ in $(seq 1 15); do
        check "https://localhost" --insecure 2>/dev/null && break
        sleep 2
    done
    check "https://localhost" --insecure
    if curl --silent --output /dev/null "http://localhost:$port/"; then
        echo "the web app is still published on :$port beside Caddy" >&2
        exit 1
    fi
fi
echo "== the install works"
