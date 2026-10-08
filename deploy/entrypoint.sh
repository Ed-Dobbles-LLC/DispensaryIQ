#!/bin/sh
# Starts crond (Curaleaf 07:00 CT daily edition) and one boot-time render, then
# hands PID 1 to Caddy exactly as the base image's CMD does (brief #5799).
umask 077
if [ -n "${CURALEAF_SCORECARD_DSN:-}" ]; then
  printf 'export CURALEAF_SCORECARD_DSN=%s\n' "'$CURALEAF_SCORECARD_DSN'" > /app/scorecard.env
fi
umask 022
crond -b -l 8
/app/curaleaf-publish.sh boot >/proc/1/fd/1 2>&1 &
exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
