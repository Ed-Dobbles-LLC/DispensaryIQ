#!/bin/sh
# Curaleaf First Page daily edition (brief #5799; brief #5807, Ed ruling #780: published
# by 09:00 CT): renders /srv/curaleaf/index.html in place from the latest complete
# audit day. "cron" mode proceeds only between 06:00 and 08:50 America/Chicago and runs
# the renderer with --attempt: a no-op once today's edition is served, a 90% short-day
# guard before 08:45 CT and a 75% hard-publish floor from 08:45 CT. "boot" mode
# (container start) skips the window so a redeploy never falls back to the committed
# snapshot. On any error the renderer leaves the served page untouched. The DSN
# (CURALEAF_SCORECARD_DSN) and SMTP password are never printed.
set -u
MODE="${1:-cron}"
ATTEMPT=""
# Brief #5852: "watch" mode = cross-watch only (daily check + Mac iMessage poller),
# every 10 min 05:00-10:00 CT, so a dead poller is noticed outside the publish window.
if [ "$MODE" = "watch" ]; then
  HM=$(TZ=America/Chicago date +%H%M | sed "s/^0*//"); HM=${HM:-0}
  if [ "$HM" -lt 500 ] || [ "$HM" -gt 1000 ]; then
    exit 0
  fi
  [ -f /app/scorecard.env ] && . /app/scorecard.env
  python3 /app/curaleaf_scorecard.py --watch
  exit 0
fi
if [ "$MODE" = "cron" ]; then
  HM=$(TZ=America/Chicago date +%H%M | sed "s/^0*//"); HM=${HM:-0}
  if [ "$HM" -lt 600 ] || [ "$HM" -gt 850 ]; then
    exit 0
  fi
  ATTEMPT="--attempt"
fi
# crond does not pass the container environment to jobs; entrypoint.sh saves it.
[ -f /app/scorecard.env ] && . /app/scorecard.env
echo "[curaleaf-publish] mode=$MODE start $(TZ=America/Chicago date '+%Y-%m-%d %H:%M %Z')"
python3 /app/curaleaf_scorecard.py --out /srv/curaleaf/index.html $ATTEMPT
echo "[curaleaf-publish] mode=$MODE exit $?"
# Brief #5851: cross-watch of the dip-service daily check (from 07:15 CT, once a day),
# separate process so it can never affect the render above.
if [ "$MODE" = "cron" ]; then
  python3 /app/curaleaf_scorecard.py --watch
fi
