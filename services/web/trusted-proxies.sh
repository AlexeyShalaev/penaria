#!/bin/sh
# Runs when the container starts. PENARIA_TRUSTED_PROXIES lists the addresses or networks
# (comma-separated, such as "10.0.0.0/8,192.168.1.2") of the reverse proxies in front of
# this container; nginx then takes the visitor's address from their X-Forwarded-For.
set -eu

target=/etc/nginx/conf.d/penaria-trusted-proxies.conf
: > "$target"
[ -n "${PENARIA_TRUSTED_PROXIES:-}" ] || exit 0

old_ifs=$IFS
IFS=,
for proxy in $PENARIA_TRUSTED_PROXIES; do
    proxy=$(printf '%s' "$proxy" | tr -d ' ')
    case "$proxy" in
        "" | *[!0-9a-fA-F.:/]*)
            echo "PENARIA_TRUSTED_PROXIES: \"$proxy\" is not an address or a network" >&2
            exit 1
            ;;
    esac
    echo "set_real_ip_from $proxy;" >> "$target"
done
IFS=$old_ifs
{
    echo "real_ip_header X-Forwarded-For;"
    echo "real_ip_recursive on;"
} >> "$target"
