#!/bin/sh
# Curaleaf First Page daily edition (brief #5799, Ed ruling #771; publish-when-complete
# per brief #5806): renders /srv/curaleaf/index.html in place from the latest complete
# audit day.
#
# "cron" mode runs every 15 minutes from 07:00 to 12:00 America/Chicago (crontab fires
# on both UTC offsets; this script drops any run outside that Central window, so DST
# is handled here). It stops once today's edition is published: the renderer writes
# "published <date>" to the status file when the edition is today's Central date. A
# short day (under 90% of the 7-date average) keeps the prior edition and the next
# attempt tries again; if today is still short at 12:00 the prior edition stays and
# its as-of line says which day it is. Every attempt appends a 'published' or 'held'
# event to ops.curaleaf_publish_events.
#
# "boot" mode (container start) skips the window so a redeploy never falls back to the
# committed snapshot. On any error the renderer leaves the served page untouched. The
# DSN (CURALEAF_SCORECARD_DSN) is never printed.
#
# Kill switch: CURALEAF_PUBLISH_RETRY_DISABLED=1 restores the single 07:00 CT run.
set -u
MODE="${1:-cron}"
STATE=/app/state
TODAY="$(TZ=America/Chicago date +%Y-%m-%d)"
HM="$(TZ=America/Chicago date +%H%M | sed 's/^0*//')"; HM="${HM:-0}"
# crond does not pass the container environment to jobs; entrypoint.sh saves it.
[ -f /app/scorecard.env ] && . /app/scorecard.env
if [ "$MODE" = "cron" ]; then
  if [ "${CURALEAF_PUBLISH_RETRY_DISABLED:-0}" = "1" ]; then
    case "$HM" in 700|701|702|703|704) ;; *) exit 0 ;; esac
  fi
  if [ "$HM" -lt 700 ] || [ "$HM" -gt 1204 ]; then
    exit 0
  fi
  if [ -f "$STATE/published-$TODAY" ]; then
    exit 0
  fi
fi
mkdir -p "$STATE"
echo "[curaleaf-publish] mode=$MODE start $(TZ=America/Chicago date '+%Y-%m-%d %H:%M %Z')"
rm -f "$STATE/status"
python3 /app/curaleaf_scorecard.py --out /srv/curaleaf/index.html \
  --status-file "$STATE/status" --event-mode "$MODE"
RC=$?
STATUS="$(cat "$STATE/status" 2>/dev/null || echo "none")"
if [ "$STATUS" = "published $TODAY" ]; then
  : > "$STATE/published-$TODAY"
fi
echo "[curaleaf-publish] mode=$MODE exit $RC status=$STATUS"
