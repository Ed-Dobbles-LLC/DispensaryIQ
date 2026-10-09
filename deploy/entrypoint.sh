#!/bin/sh
# Starts crond (Curaleaf daily edition, published by 09:00 CT) and one boot-time render, then
# hands PID 1 to Caddy exactly as the base image's CMD does (brief #5799).
umask 077
: > /app/scorecard.env
for v in CURALEAF_SCORECARD_DSN SCORECARD_SMTP_HOST SCORECARD_SMTP_PORT SCORECARD_SMTP_USER \
         SCORECARD_SMTP_PASSWORD CURALEAF_EMAIL_DISABLED CURALEAF_PAGE_URL; do
  eval "val=\${$v:-}"
  if [ -n "$val" ]; then
    printf "export %s='%s'\n" "$v" "$(printf '%s' "$val" | sed "s/'/'\\\\''/g")" >> /app/scorecard.env
  fi
done
umask 022
crond -b -l 8
/app/curaleaf-publish.sh boot >/proc/1/fd/1 2>&1 &
exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
