#!/usr/bin/env bash
# Brings the Compose install up from this checkout and checks that it works; CI runs it.
#   deploy/compose/smoke-test.sh          the plain install on PENARIA_PORT (18080 by default)
#   deploy/compose/smoke-test.sh --https  then also the HTTPS overlay, on ports 80 and 443
# It uses a Compose project of its own, so an install on this machine is left alone.
set -euo pipefail
cd "$(dirname "$0")"

port=${PENARIA_PORT:-18080}
env_file=$(mktemp)
work=$(mktemp -d)
# Smaller than the default, so the test can send files over it.
max_size=5242880
project=(docker compose --project-name penaria-smoke-test --env-file "$env_file" -f compose.yaml -f compose.build.yaml)

cleanup() {
    status=$?
    if [ "$status" -ne 0 ]; then
        "${project[@]}" -f compose.https.yaml logs --no-color --tail 200 || true
    fi
    "${project[@]}" -f compose.https.yaml down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$env_file" "$work"
    exit "$status"
}
trap cleanup EXIT

# Made once: the database keeps the password it was created with.
secret_key=$(openssl rand -hex 32)
postgres_password=$(openssl rand -hex 24)
s3_password=$(openssl rand -hex 24)

write_env() {
    cat > "$env_file" <<ENV
PENARIA_PUBLIC_URL=$1
PENARIA_SECRET_KEY=$secret_key
POSTGRES_PASSWORD=$postgres_password
S3_PASSWORD=$s3_password
PENARIA_FILES__MAX_SIZE=$max_size
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

# A field of the JSON object on stdin.
field() {
    python3 -c 'import json, sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"
}

# A call of the API through the web app, signed in, as the browser sends it.
api() {
    curl --silent --show-error --fail-with-body --cookie "$work/cookies" --cookie-jar "$work/cookies" \
        --header "Origin: http://localhost:$port" "$@"
}

# Sends a file of that many bytes; it must be refused as too large.
refused_as_too_large() {
    head -c "$1" /dev/zero > "$work/large.bin"
    status=$(curl --silent --cookie "$work/cookies" --header "Origin: http://localhost:$port" \
        --output "$work/refusal.json" --write-out '%{http_code}' --form "file=@$work/large.bin" "$2")
    if [ "$status" != 413 ] || [ "$(field code < "$work/refusal.json")" != file_too_large ]; then
        echo "a file of $1 bytes was answered $status: $(cat "$work/refusal.json")" >&2
        exit 1
    fi
}

# Set up, add a photo through the web app, and see it cleaned and previewed by the worker.
check_files() {
    base="http://localhost:$port/api/v1"
    token=$("${project[@]}" logs penaria-server | sed -n 's/.*setup token \([0-9a-f]*\).*/\1/p' | tail -1)
    api --json "{\"token\": \"$token\", \"username\": \"smoke\", \"display_name\": \"Smoke\",
        \"password\": \"a password of the smoke test\", \"locale\": \"en\"}" "$base/setup" >/dev/null
    home=$(api --json '{"name": "Smoke", "timezone": "UTC", "locale": "en"}' "$base/homes" | field id)
    place=$(api --json '{"kind": "property", "name": "Smoke"}' "$base/homes/$home/entities" | field id)

    # A photo that says where it was taken, made by the server's own Pillow: nothing real.
    "${project[@]}" exec -T penaria-server python -c '
import io, sys
from PIL import Image
exif = Image.Exif()
exif[0x010F] = "SECRET-CAMERA"
exif.get_ifd(0x8825)[27] = b"SECRET-PLACE"
out = io.BytesIO()
Image.new("RGB", (2000, 1500), "teal").save(out, "JPEG", exif=exif)
sys.stdout.buffer.write(out.getvalue())' > "$work/photo.jpg"
    grep --quiet SECRET-PLACE "$work/photo.jpg"

    # Over 1 MB, so the upload shows nginx lets files through that other requests may not be.
    cat "$work/photo.jpg" > "$work/padded.jpg"
    head -c 3000000 /dev/zero >> "$work/padded.jpg"
    upload="$base/entities/$place/files?kind=photo"
    file=$(api --form "file=@$work/padded.jpg" "$upload" | field id)
    for _ in $(seq 1 60); do
        state=$(api "$base/files/$file" | field status)
        [ "$state" = processing ] || break
        sleep 1
    done
    [ "$state" = ready ] || { echo "the photo is $state, not ready" >&2; exit 1; }
    api --output "$work/stored.jpg" "$base/files/$file/content"
    if grep --quiet SECRET "$work/stored.jpg"; then
        echo "the stored photo still says where it was taken" >&2
        exit 1
    fi
    for size in 320 1600; do
        served=$(api --output "$work/preview.webp" --write-out '%{content_type}' "$base/files/$file/preview/$size")
        [ "$served" = image/webp ] || { echo "the preview of $size is $served" >&2; exit 1; }
    done

    # Just over the limit the server refuses; far over it, nginx does, with the same answer.
    other="$base/entities/$place/files?kind=other"
    refused_as_too_large $((max_size + 1000)) "$other"
    refused_as_too_large $((max_size + 2000000)) "$other"
}

echo "== the plain install"
write_env "http://localhost:$port"
"${project[@]}" up --detach --build --wait
check "http://localhost:$port"
# The setup screen tells people to find the token exactly like this.
"${project[@]}" logs penaria-server | grep --quiet "setup token"
"${project[@]}" exec -T penaria-server python -m penaria.apps.cli --help >/dev/null

echo "== files"
check_files

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
