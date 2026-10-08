#!/bin/sh
# Starts crond (Curaleaf daily edition, 07:00-12:00 CT every 15 min) and one boot-time render, then
# hands PID 1 to Caddy exactly as the base image's CMD does (brief #5799).
umask 077
if [ -n "${CURALEAF_SCORECARD_DSN:-}" ]; then
  printf 'export CURALEAF_SCORECARD_DSN=%s\n' "'$CURALEAF_SCORECARD_DSN'" > /app/scorecard.env
fi
# Brief #5806 kill switch for the 07:00-12:00 CT retry loop (1 = single 07:00 run).
printf 'export CURALEAF_PUBLISH_RETRY_DISABLED=%s\n' "'${CURALEAF_PUBLISH_RETRY_DISABLED:-0}'" >> /app/scorecard.env
umask 022
crond -b -l 8
/app/curaleaf-publish.sh boot >/proc/1/fd/1 2>&1 &
exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
