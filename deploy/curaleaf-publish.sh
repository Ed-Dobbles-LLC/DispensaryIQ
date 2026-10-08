#!/bin/sh
# Curaleaf First Page daily edition (brief #5799, Ed ruling #771): renders
# /srv/curaleaf/index.html in place from the latest complete audit day.
# Cron fires at 12:00 and 13:00 UTC; the "cron" mode proceeds only when the
# America/Chicago hour is 07, so the edition publishes at 07:00 CT in both CDT and
# CST. "boot" mode (container start) skips the hour guard so a redeploy never
# falls back to the committed snapshot. On any error the renderer leaves the
# served page untouched. The DSN (CURALEAF_SCORECARD_DSN) is never printed.
set -u
MODE="${1:-cron}"
if [ "$MODE" = "cron" ] && [ "$(TZ=America/Chicago date +%H)" != "07" ]; then
  exit 0
fi
# crond does not pass the container environment to jobs; entrypoint.sh saves it.
[ -f /app/scorecard.env ] && . /app/scorecard.env
echo "[curaleaf-publish] mode=$MODE start $(TZ=America/Chicago date '+%Y-%m-%d %H:%M %Z')"
python3 /app/curaleaf_scorecard.py --out /srv/curaleaf/index.html
echo "[curaleaf-publish] mode=$MODE exit $?"
