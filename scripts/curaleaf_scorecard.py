"""
Daily edition of the Curaleaf Project First Page scorecard at /curaleaf/ (brief #5798,
Ed ruling Historian #767: the served scorecard updates DAILY).

Until this script existed, site/curaleaf/index.html was a hand-built static page
(commit eab62a4, 2026-10-02) with its numbers typed in, so it froze at
"AS OF FRI OCT 2, 2026 07:22 CT". This script recomputes the same page from the same
source: the logic of dsps.v_firstpage_scorecard_latest (independent panel, dedup,
validated-platform run_ids, latest read per door x category x brand over the edition
date and the two days before it), parameterized on an edition date instead of
CURRENT_DATE so an edition is reproducible for any date.

Definitions, door universe, exclusions, DATA ISSUE handling and labels are the ones the
hand-built page carries; nothing here changes a metric definition.

Edition date = the latest audit date <= today in America/Chicago, taken from
(now() AT TIME ZONE 'America/Chicago')::date in SQL (never CURRENT_DATE), whose door count is at
least 90% of the trailing 7-date average. A short day keeps the previous day's edition
and logs why; a partial day is never published as current.

09:00 CT hard deadline (brief #5807, Ed ruling Historian #780): cron runs --attempt
every 10 min from 06:00 to 08:50 CT and stops once today's edition is served. From
08:45 CT (the hard publish) today's edition is published if it has at least 75% of
the 7-date average doors (the as-of line states doors read of panel doors); under
75% the prior edition is kept and a 'held' event is recorded. Every published / held
/ short attempt is logged to ops.curaleaf_publish_events.

Email on publish (brief #5807 TASK 3): when today's edition publishes (never a held or
prior edition), one email per edition date goes to each ops.curaleaf_subscribers row
with approved_by_ed AND unsubscribed_at IS NULL, idempotent through
ops.curaleaf_publish_events ('email_sent' per edition + address). SMTP comes from
SCORECARD_SMTP_HOST/PORT/USER/PASSWORD; while they are unset the send is skipped and
'email_skipped_no_credentials' is logged; an email problem never fails the publish.
Kill switch: CURALEAF_EMAIL_DISABLED=1.

Cross-watch (brief #5851 FIRST-PAGE-CLOCK-1, TASK 2): --watch, run by the cron path after
each publish attempt, in its own process so it can never touch the render. At the first
tick at/after 07:15 CT, if ops.curaleaf_daily_check_log has no row since 06:00 CT today
(the dip-service daily check, on the dip-service Railway tick), it DMs Ed "First Page
check has not run today" via chat.postMessage with SLACK_USER_TOKEN /
SLACK_ED_DM_CHANNEL_ID, read through ops.fn_firstpage_alert_creds() (this role has no
SELECT on ops.secrets). Once per day, guarded by a 'check_missing_alert' row in
ops.curaleaf_publish_events. Two Railway projects watch each other.
Kill switch: CURALEAF_WATCH_DISABLED=1.

iMessage (brief #5852 IMESSAGE-ALERT-1): the check-missing alert also queues a text to Ed
through ops.fn_enqueue_alert() (SECURITY DEFINER; resolves ED_IMESSAGE_HANDLE itself), which
the launchd poller on the Mac mini sends. --watch also checks that poller: from 05:00 to
10:00 CT, if ops.alert_poller_heartbeat has no row seen in the last 20 min, it DMs Ed on
Slack (a dead poller cannot text), once per day ('poller_dead_alert' event). The cron path
runs --watch every 10 min 05:00-10:00 CT (curaleaf-publish.sh watch).

Usage:
    python3 scripts/curaleaf_scorecard.py --out site/curaleaf/index.html          # live (Neon HTTP SQL)
    python3 scripts/curaleaf_scorecard.py --watch                                 # cross-watch (cron)
    python3 scripts/curaleaf_scorecard.py --print-sql --date 2026-10-07           # emit the metrics SQL
    python3 scripts/curaleaf_scorecard.py --from-json m.json --out index.html     # render saved metrics

Env: CURALEAF_SCORECARD_DSN (falls back to DIP_DATABASE_URL). Stdlib only.
Exit codes: 0 rendered (or kept the previous edition on a short day), 2 no DSN, 1 error.
On any error the existing page is left untouched.
"""

import argparse
import datetime as dt
import email.message
import email.utils
import fcntl
import html
import json
import math
import os
import smtplib
import sys
import tempfile
import urllib.request

SHORT_DAY_RATIO = 0.90
HARD_RATIO = 0.75          # 08:45 CT hard publish floor (brief #5807)
HARD_HM = 845              # America/Chicago HHMM from which HARD_RATIO applies to today
PAGE_URL = os.environ.get("CURALEAF_PAGE_URL", "https://curaleaf.dispensaryintelligence.com/")
SENDER = '"DispensaryIntelligence" <ed@dispensaryintelligence.com>'
TARGET = 0.80
TREND_DAYS = 11

PLATFORM_RUNS = r"^(dutchie-residential|jane-(direct|residential)|sweed-(daily|direct)|carrot-daily|joint-daily)"
CHAIN_RE = (
    r"curaleaf|\mrise\M|verilife|sunnyside|ascend|acreage|columbia care|cannabist|zen leaf|verano|"
    r"\mayr\M|jushi|beyond hello|greenthumb|\mgti\M|cresco|trulieve|terrasana|liberty|apothecarium|"
    r"etain|\mmpx\M|theory wellness|the botanist"
)
COMPETITOR_EXCLUDE = ("anthem", "b noble", "b_noble", "find", "select", "grassroots", "jams", "curaleaf")
BRAND_LABEL = {"anthem": "Anthem", "b_noble": "B Noble", "find": "FIND", "select": "Select",
               "grassroots": "Grassroots", "jams": "JAMS", "curaleaf": "Curaleaf"}
CAT_LABEL = {"pre_roll": "Pre-roll", "preroll": "Pre-roll", "pre-roll": "Pre-roll"}
STATE_ORDER = ("NY", "NJ", "IL")


def log(msg):
    print(f"[curaleaf-scorecard] {msg}", file=sys.stderr, flush=True)


# The edition date is always the Central date, computed in SQL (brief #5799): never
# CURRENT_DATE, which is the UTC date on Neon and runs a day ahead after 19:00 CT.
CT_TODAY_SQL = "(now() AT TIME ZONE 'America/Chicago')::date"


# Panel + window rows: dsps.v_firstpage_scorecard_latest's CTEs verbatim, with the
# CURRENT_DATE window replaced by an explicit [lo, hi] audit_date range (SQL date expressions).
def _panel_rows_sql(lo, hi):
    return f"""
ind AS (
  SELECT did::bigint AS dispensary_id, state FROM ops.independent_panel_20260831 WHERE class = 'INDEPENDENT'
  UNION
  SELECT c.dispensary_id::bigint, d.state FROM ops.nj_expansion_candidates c
    JOIN dim_dispensary d ON d.dispensary_id::bigint = c.dispensary_id::bigint
), ind2 AS (
  SELECT i.dispensary_id, i.state,
    row_number() OVER (PARTITION BY COALESCE(NULLIF(lower(regexp_replace(d.address::text, '[^a-z0-9]', '', 'gi')), ''),
                       lower(trim(d.dispensary_name)) || '|' || lower(COALESCE(d.city, ''))) ORDER BY i.dispensary_id) AS dup_rn,
    row_number() OVER (PARTITION BY COALESCE(ds.dutchie_dispensary_id, 'door-' || i.dispensary_id::text) ORDER BY i.dispensary_id) AS menu_rn
  FROM ind i
  JOIN dim_dispensary d ON d.dispensary_id::bigint = i.dispensary_id
  LEFT JOIN dispensaries ds ON ds.id = i.dispensary_id
  LEFT JOIN ops.pfp_ownership_20260923 o ON o.dispensary_id = i.dispensary_id
  WHERE COALESCE(d.dispensary_name, '') !~* '{CHAIN_RE}'
    AND COALESCE(d.chain_name, '') !~* '{CHAIN_RE}'
    AND o.dispensary_id IS NOT NULL AND o.verdict IN ('RETAIL_ONLY', 'CANNOT_DETERMINE')
    AND i.dispensary_id <> 37360912
), raw AS (
  SELECT a.dispensary_id, a.audit_date, a.audit_ts, a.category_canonical, a.brand_key, a.brand_present,
         a.on_page_1, a.first_product_rank, a.brand_skus_on_page_1, a.competitors_ahead, a.page_1_n,
         a.status, i.state, split_part(a.run_id, '-', 1) AS platform
  FROM dsps.fact_first_page_audit a
  JOIN ind2 i ON i.dispensary_id = a.dispensary_id::bigint AND i.dup_rn = 1
             AND (split_part(a.run_id, '-', 1) <> 'dutchie' OR i.menu_rn = 1)
  WHERE a.audit_date BETWEEN {lo} AND {hi} AND a.run_id ~ '{PLATFORM_RUNS}'
)"""


def door_counts_sql():
    return f"""WITH {_panel_rows_sql(CT_TODAY_SQL + " - 20", CT_TODAY_SQL)}
SELECT {CT_TODAY_SQL}::text AS ct_today, to_char(now() AT TIME ZONE 'America/Chicago', 'HH24MI') AS ct_hm, c.d, c.doors
FROM (SELECT 1) one LEFT JOIN (SELECT audit_date::text AS d, count(DISTINCT dispensary_id) AS doors FROM raw GROUP BY 1) c ON true
ORDER BY c.d DESC"""


def pick_edition(counts, ct_today, today_ratio=SHORT_DAY_RATIO):
    """counts: [(date_str, doors)] newest first. Returns (edition_date, reason).
    today_ratio applies to ct_today only (HARD_RATIO from 08:45 CT); older dates
    always need SHORT_DAY_RATIO."""
    counts = [(dt.date.fromisoformat(d[:10]), int(n)) for d, n in counts]
    counts = [c for c in counts if c[0] <= ct_today]
    for i, (d, n) in enumerate(counts):
        prior = [m for _, m in counts[i + 1:i + 8]]
        avg = sum(prior) / len(prior) if prior else 0
        ratio = today_ratio if d == ct_today else SHORT_DAY_RATIO
        if not prior or n >= ratio * avg:
            return d, (f"{d}: {n} doors vs 7-date avg {avg:.0f} ({n / avg:.0%}, floor {ratio:.0%})" if prior
                       else f"{d}: no prior history")
        log(f"short day {d}: {n} doors < {ratio:.0%} of 7-date avg {avg:.0f}; keeping previous day's edition")
    raise RuntimeError("no audit date passes the short-day guard")


def metrics_sql(edition):
    d = edition.isoformat()
    lo = (edition - dt.timedelta(days=TREND_DAYS + 3)).isoformat()
    excl = ", ".join(f"'{b}'" for b in COMPETITOR_EXCLUDE)
    return f"""WITH {_panel_rows_sql(f"date '{lo}'", f"date '{d}'")},
win AS (SELECT *, row_number() OVER (PARTITION BY dispensary_id, category_canonical, brand_key ORDER BY audit_ts DESC) AS rn
        FROM raw WHERE audit_date BETWEEN date '{d}' - 2 AND date '{d}'),
v AS (SELECT * FROM win WHERE rn = 1),
dly AS (SELECT *, row_number() OVER (PARTITION BY audit_date, dispensary_id, category_canonical, brand_key ORDER BY audit_ts DESC) AS rn
        FROM raw WHERE status <> 'DATA ISSUE'),
dd AS (SELECT audit_date, dispensary_id, bool_or(on_page_1 AND brand_present) AS p1,
              bool_or(on_page_1 AND brand_present AND brand_key NOT IN ('anthem', 'b_noble')) AS p1_4
       FROM dly WHERE rn = 1 GROUP BY 1, 2),
days AS (SELECT DISTINCT audit_date FROM dd ORDER BY 1 DESC LIMIT {TREND_DAYS}),
pages AS (SELECT dispensary_id, category_canonical, max(page_1_n) AS n FROM v WHERE status <> 'DATA ISSUE' GROUP BY 1, 2),
last_read AS (SELECT dispensary_id, max(audit_date) AS d FROM v GROUP BY 1),
p1 AS (SELECT * FROM v WHERE on_page_1 AND brand_present)
SELECT json_build_object(
  'edition', '{d}',
  'built_at', to_char(now() AT TIME ZONE 'America/Chicago', 'YYYY-MM-DD"T"HH24:MI'),
  'panel', (SELECT count(DISTINCT dispensary_id) FROM ind2 WHERE dup_rn = 1),
  'captured', (SELECT count(DISTINCT dispensary_id) FROM v),
  'scored', (SELECT count(DISTINCT dispensary_id) FROM v WHERE status <> 'DATA ISSUE'),
  'read_today', (SELECT count(*) FROM last_read WHERE d = date '{d}'),
  'doors_p1', (SELECT count(DISTINCT dispensary_id) FROM p1),
  'doors_p1_4', (SELECT count(DISTINCT dispensary_id) FROM p1 WHERE brand_key NOT IN ('anthem', 'b_noble')),
  'placements', (SELECT count(*) FROM p1),
  'doors_r1', (SELECT count(DISTINCT dispensary_id) FROM v WHERE brand_present AND first_product_rank = 1),
  'doors_top5', (SELECT count(DISTINCT dispensary_id) FROM v WHERE brand_present AND first_product_rank BETWEEN 1 AND 5),
  'avg_rank', (SELECT round(avg(first_product_rank)::numeric, 1) FROM p1),
  'median_rank', (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY first_product_rank) FROM p1),
  'page_n_min', (SELECT min(n) FROM pages WHERE n > 0), 'page_n_max', (SELECT max(n) FROM pages),
  'skus_p1', (SELECT COALESCE(sum(brand_skus_on_page_1), 0) FROM p1),
  'slots', (SELECT COALESCE(sum(n), 0) FROM pages),
  'avg_ahead', (SELECT round(avg(jsonb_array_length(competitors_ahead))::numeric, 1) FROM p1),
  'states', (SELECT json_agg(s) FROM (
      SELECT state, count(DISTINCT dispensary_id) FILTER (WHERE status <> 'DATA ISSUE') AS scored,
             count(DISTINCT dispensary_id) FILTER (WHERE on_page_1 AND brand_present) AS p1,
             round(avg(first_product_rank) FILTER (WHERE on_page_1 AND brand_present)::numeric, 1) AS avg_rank
      FROM v GROUP BY state ORDER BY 2 DESC) s),
  'matrix', (SELECT json_agg(m) FROM (
      SELECT brand_key, category_canonical, count(DISTINCT dispensary_id) FILTER (WHERE on_page_1) AS doors_p1,
             count(DISTINCT dispensary_id) FILTER (WHERE first_product_rank = 1) AS doors_r1,
             round(avg(first_product_rank) FILTER (WHERE on_page_1)::numeric, 1) AS avg_rank
      FROM v WHERE brand_present AND brand_key <> 'curaleaf'
      GROUP BY 1, 2 HAVING count(DISTINCT dispensary_id) FILTER (WHERE on_page_1) >= 10 ORDER BY 3 DESC, 4 DESC) m),
  'b_noble_p1', (SELECT count(DISTINCT dispensary_id) FROM p1 WHERE brand_key = 'b_noble'),
  'sv_doors', (SELECT count(DISTINCT dispensary_id) FROM v WHERE brand_key = 'select' AND category_canonical = 'vape' AND status <> 'DATA ISSUE'),
  'sv_p1', (SELECT count(DISTINCT dispensary_id) FROM p1 WHERE brand_key = 'select' AND category_canonical = 'vape'),
  'sv_rank', (SELECT round(avg(first_product_rank)::numeric, 1) FROM p1 WHERE brand_key = 'select' AND category_canonical = 'vape'),
  'sv_skus', (SELECT COALESCE(sum(brand_skus_on_page_1), 0) FROM p1 WHERE brand_key = 'select' AND category_canonical = 'vape'),
  'vape_slots', (SELECT COALESCE(sum(n), 0) FROM pages WHERE category_canonical = 'vape'),
  'competitors', (SELECT json_agg(c) FROM (
      SELECT comp->>'brand' AS brand, count(*) AS n FROM p1, jsonb_array_elements(competitors_ahead) comp
      WHERE COALESCE(trim(comp->>'brand'), '') <> '' AND lower(comp->>'brand') NOT IN ({excl}) GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 7) c),
  'trend', (SELECT json_agg(t ORDER BY t.d) FROM (
      SELECT dd.audit_date::text AS d, count(*) AS scored, count(*) FILTER (WHERE p1) AS p1, count(*) FILTER (WHERE p1_4) AS p1_4
      FROM dd JOIN days USING (audit_date) GROUP BY 1) t),
  'dod', (SELECT json_build_object('y', y.audit_date::text, 't', t.audit_date::text, 'both', count(*),
                                   'on', count(*) FILTER (WHERE t.p1 AND NOT y.p1), 'off', count(*) FILTER (WHERE y.p1 AND NOT t.p1))
          FROM dd t JOIN dd y ON y.dispensary_id = t.dispensary_id
          WHERE t.audit_date = date '{d}' AND y.audit_date = (SELECT max(audit_date) FROM days WHERE audit_date < date '{d}')
          GROUP BY y.audit_date, t.audit_date)
) AS m"""


def neon_sql(dsn, query, params=None):
    host = dsn.split("@")[1].split("/")[0].split(":")[0]
    req = urllib.request.Request(
        f"https://{host}/sql", data=json.dumps({"query": query, "params": params or []}).encode(),
        headers={"Content-Type": "application/json", "Neon-Connection-String": dsn},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r).get("rows", [])


# ---------------------------------------------------------------- publish events + email (brief #5807)

def served_edition(path):
    """Edition date of the page currently served at `path` (its trailing marker), or None."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    i = text.rfind("curaleaf-scorecard edition=")
    if i < 0:
        return None
    try:
        return dt.date.fromisoformat(text[i + len("curaleaf-scorecard edition="):][:10])
    except ValueError:
        return None


def log_event(dsn, kind, detail):
    """Append one row to ops.curaleaf_publish_events; never raises."""
    try:
        neon_sql(dsn, "INSERT INTO ops.curaleaf_publish_events (kind, detail) VALUES ($1, $2::jsonb)",
                 [kind, json.dumps(detail)])
    except Exception as e:  # noqa: BLE001
        log(f"could not log {kind} event: {e!r}")


def has_event(dsn, kind, edition, email_addr=None):
    q = ("SELECT count(*) AS n FROM ops.curaleaf_publish_events WHERE kind = $1 AND detail->>'edition' = $2"
         + (" AND detail->>'email' = $3" if email_addr else ""))
    params = [kind, edition] + ([email_addr] if email_addr else [])
    return int(neon_sql(dsn, q, params)[0]["n"]) > 0


# ---------------------------------------------------------------- cross-watch (brief #5851)

WATCH_HM = 715             # America/Chicago HHMM from which a missing daily check alerts
WATCH_SQL = """
SELECT to_char(now() AT TIME ZONE 'America/Chicago', 'HH24MI')::int AS ct_hm,
       ((now() AT TIME ZONE 'America/Chicago')::date)::text AS ct_today,
       (SELECT count(*) FROM ops.curaleaf_daily_check_log
         WHERE run_at >= (((now() AT TIME ZONE 'America/Chicago')::date + time '06:00')
                          AT TIME ZONE 'America/Chicago')) AS checks,
       (SELECT count(*) FROM ops.curaleaf_publish_events
         WHERE kind = 'check_missing_alert'
           AND event_at >= (((now() AT TIME ZONE 'America/Chicago')::date)::timestamp
                            AT TIME ZONE 'America/Chicago')) AS alerted"""


def slack_dm(dsn, text, opener=urllib.request.urlopen):
    """chat.postMessage to Ed's DM; returns 'sent (ts=...)' / 'skipped: ...' / 'failed: ...'."""
    try:
        creds = neon_sql(dsn, "SELECT slack_token, slack_channel FROM ops.fn_firstpage_alert_creds()")
    except Exception as e:  # noqa: BLE001
        return f"failed: creds {type(e).__name__}"
    token = (creds[0].get("slack_token") or "").strip() if creds else ""
    channel = (creds[0].get("slack_channel") or "").strip() if creds else ""
    if not token or not channel:
        return "skipped: no SLACK_USER_TOKEN / SLACK_ED_DM_CHANNEL_ID in ops.secrets"
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage", data=json.dumps({"channel": channel, "text": text}).encode(),
        headers={"Content-Type": "application/json; charset=utf-8", "Authorization": f"Bearer {token}"})
    try:
        with opener(req, timeout=20) as r:
            res = json.load(r)
    except Exception as e:  # noqa: BLE001
        return f"failed: {type(e).__name__}"
    return f"sent (ts={res.get('ts')})" if res.get("ok") else f"failed: {res.get('error')}"


def watch(dsn, sql=None, dm=None, text_ed=None):
    """One cross-watch tick. Returns a short status string; never raises."""
    sql = sql or neon_sql
    dm = dm or slack_dm
    if os.environ.get("CURALEAF_WATCH_DISABLED", "").strip().lower() in ("1", "true", "yes", "on"):
        return "disabled"
    try:
        r = sql(dsn, WATCH_SQL)[0]
    except Exception as e:  # noqa: BLE001
        return f"error: {type(e).__name__}"
    if int(r["ct_hm"]) < WATCH_HM:
        return "before 07:15 CT"
    if int(r["checks"]) > 0:
        return f"ok: {r['checks']} check rows since 06:00 CT"
    if int(r["alerted"]) > 0:
        return "missing; already alerted today"
    text = (f"First Page check has not run today ({r['ct_today']}, {int(r['ct_hm']):04d} CT): "
            "no ops.curaleaf_daily_check_log row since 06:00 CT. dip-service tick "
            "(org_worker.firstpage_check) may be down. Sent by the DispensaryIQ cross-watch.")
    res = dm(dsn, text)
    imsg = (text_ed or enqueue_text)(
        dsn, f"check_missing:{r['ct_today']}:07:15",
        f"First Page check NOT RUN {fmd(r['ct_today'])} - dip-service tick may be down (DispensaryIQ cross-watch)")
    log_event(dsn, "check_missing_alert",
              {"ct_today": r["ct_today"], "ct_hm": int(r["ct_hm"]), "dm": res, "imessage": imsg})
    return f"missing; alert {res}; imessage {imsg}"


def fmd(iso_day):
    d = dt.date.fromisoformat(iso_day)
    return f"{d.month}/{d.day}"


def enqueue_text(dsn, dedupe_key, body):
    """Queue one iMessage to Ed via ops.fn_enqueue_alert (brief #5852). Never raises."""
    try:
        rows = neon_sql(dsn, "SELECT ops.fn_enqueue_alert($1, $2) AS id", [dedupe_key, body])
    except Exception as e:  # noqa: BLE001
        return f"failed: {type(e).__name__}"
    rid = rows[0].get("id") if rows else None
    return f"queued id={rid}" if rid is not None else "not queued (duplicate key or no ED_IMESSAGE_HANDLE)"


POLLER_WINDOW = (500, 1000)   # America/Chicago HHMM window in which a dead poller alerts
POLLER_STALE_MIN = 20
POLLER_SQL = """
SELECT to_char(now() AT TIME ZONE 'America/Chicago', 'HH24MI')::int AS ct_hm,
       ((now() AT TIME ZONE 'America/Chicago')::date)::text AS ct_today,
       (SELECT round(extract(epoch FROM now() - max(seen_at)) / 60)::int
          FROM ops.alert_poller_heartbeat) AS age_min,
       (SELECT count(*) FROM ops.curaleaf_publish_events
         WHERE kind = 'poller_dead_alert'
           AND event_at >= (((now() AT TIME ZONE 'America/Chicago')::date)::timestamp
                            AT TIME ZONE 'America/Chicago')) AS alerted"""


def poller_watch(dsn, sql=None, dm=None):
    """Brief #5852: Slack-DM Ed once a day when the Mac iMessage poller's heartbeat is
    older than 20 min between 05:00 and 10:00 CT. Returns a short status; never raises."""
    sql = sql or neon_sql
    dm = dm or slack_dm
    if os.environ.get("CURALEAF_WATCH_DISABLED", "").strip().lower() in ("1", "true", "yes", "on"):
        return "disabled"
    try:
        r = sql(dsn, POLLER_SQL)[0]
    except Exception as e:  # noqa: BLE001
        return f"error: {type(e).__name__}"
    if not (POLLER_WINDOW[0] <= int(r["ct_hm"]) <= POLLER_WINDOW[1]):
        return "outside 05:00-10:00 CT"
    age = r.get("age_min")
    if age is not None and int(age) <= POLLER_STALE_MIN:
        return f"ok: heartbeat {age} min ago"
    if int(r["alerted"]) > 0:
        return "stale; already alerted today"
    seen = "never" if age is None else f"{age} min ago"
    text = (f"iMessage alert poller on the Mac mini is DOWN (last heartbeat {seen}; "
            f"{r['ct_today']} {int(r['ct_hm']):04d} CT): First Page texts will not arrive. "
            "Re-run dip-service alert-poller-install.yml (action=install) or check the Mac. "
            "Sent by the DispensaryIQ cross-watch.")
    res = dm(dsn, text)
    log_event(dsn, "poller_dead_alert", {"ct_today": r["ct_today"], "ct_hm": int(r["ct_hm"]),
                                         "age_min": age, "dm": res})
    return f"stale; alert {res}"


def fdate_email(d):
    return f"{d.strftime('%A')} {d.strftime('%b')} {d.day}"


def email_content(m):
    """(subject, text, html) from the metrics of the render that was just published."""
    ed = dt.date.fromisoformat(m["edition"])
    day = fdate_email(ed)
    subject = f"Curaleaf First Page - {day} edition is live"
    text = (f"The {day} edition of your Project First Page scorecard is live: {PAGE_URL}. "
            f"Pre-certification read: {m['read_today']} of {m['panel']} panel doors read; "
            f"Curaleaf on Page 1 at {m['doors_p1']} of {m['scored']} doors. Reply to unsubscribe.")
    body = (f'<p>The {esc(day)} edition of your Project First Page scorecard is live: '
            f'<a href="{esc(PAGE_URL)}">{esc(PAGE_URL)}</a>.</p>'
            f"<p>Pre-certification read: {esc(m['read_today'])} of {esc(m['panel'])} panel doors read; "
            f"Curaleaf on Page 1 at {esc(m['doors_p1'])} of {esc(m['scored'])} doors.</p>"
            f"<p>Reply to unsubscribe.</p>")
    return subject, text, body


def send_publish_emails(dsn, m, smtp_factory=None):
    """One email per approved subscriber per edition date. Never raises."""
    edition = m["edition"]
    try:
        if (os.environ.get("CURALEAF_EMAIL_DISABLED") or "").strip().lower() in ("1", "true", "yes", "on"):
            if not has_event(dsn, "email_skipped_disabled", edition):
                log_event(dsn, "email_skipped_disabled", {"edition": edition})
            return "disabled"
        subs = [r["email"] for r in neon_sql(
            dsn, "SELECT email FROM ops.curaleaf_subscribers WHERE approved_by_ed = true AND unsubscribed_at IS NULL "
                 "ORDER BY email")]
        todo = [a for a in subs if not has_event(dsn, "email_sent", edition, a)]
        if not todo:
            return "nothing to send"
        host = os.environ.get("SCORECARD_SMTP_HOST")
        user = os.environ.get("SCORECARD_SMTP_USER")
        password = os.environ.get("SCORECARD_SMTP_PASSWORD")
        if not (host and user and password):
            if not has_event(dsn, "email_skipped_no_credentials", edition):
                log_event(dsn, "email_skipped_no_credentials", {"edition": edition, "recipients": len(todo)})
            return "skipped: no SMTP credentials"
        port = int(os.environ.get("SCORECARD_SMTP_PORT") or 587)
        subject, text, body = email_content(m)
        factory = smtp_factory or (smtplib.SMTP_SSL if port == 465 else smtplib.SMTP)
        sent = 0
        with factory(host, port, timeout=30) as smtp:
            if port != 465 and smtp_factory is None:
                smtp.starttls()
            smtp.login(user, password)
            for addr in todo:
                msg = email.message.EmailMessage()
                msg["From"] = SENDER
                msg["To"] = addr
                msg["Subject"] = subject
                msg["Date"] = email.utils.formatdate(localtime=False)
                msg["Message-ID"] = email.utils.make_msgid(domain="dispensaryintelligence.com")
                msg.set_content(text)
                msg.add_alternative(f"<html><body>{body}</body></html>", subtype="html")
                try:
                    smtp.send_message(msg)
                    log_event(dsn, "email_sent", {"edition": edition, "email": addr})
                    sent += 1
                except Exception as e:  # noqa: BLE001
                    log_event(dsn, "email_failed", {"edition": edition, "email": addr, "error": type(e).__name__})
        return f"sent {sent} of {len(todo)}"
    except Exception as e:  # noqa: BLE001 -- an email problem never fails the publish
        log(f"email step error {e!r}")
        log_event(dsn, "email_failed", {"edition": edition, "error": type(e).__name__})
        return f"error {type(e).__name__}"


def after_render(dsn, m, ct_today, ct_hm, attempt, why):
    """Publish bookkeeping once the page is written: a 'published' event + emails for
    today's edition; a 'held' (from 08:45 CT) or 'attempt_short' event otherwise."""
    edition = dt.date.fromisoformat(m["edition"])
    if edition == ct_today:
        if not has_event(dsn, "published", m["edition"]):
            log_event(dsn, "published", {
                "edition": m["edition"], "doors_read": m["read_today"], "panel_doors": m["panel"],
                "p1": m["doors_p1"], "p1_denom": m["scored"], "hard": ct_hm >= HARD_HM, "why": why})
        log(f"email: {send_publish_emails(dsn, m)}")
    elif attempt:
        kind = "held" if ct_hm >= HARD_HM else "attempt_short"
        log_event(dsn, kind, {"edition": ct_today.isoformat(), "kept": m["edition"], "ct_hm": f"{ct_hm:04d}",
                              "reason": why})


# ---------------------------------------------------------------- rendering

def esc(s):
    return html.escape(str(s))


def pct(a, b):
    return round(100 * a / b) if b else 0


def fdate_long(d):
    return d.strftime("%a %b %-d, %Y")


def fdate_short(d):
    return d.strftime("%a %b %-d")


def rk(v):
    return "—" if v is None else f"{float(v):.1f}"


def label_brand(k):
    return BRAND_LABEL.get(k, k)


def label_cat(c):
    return CAT_LABEL.get(c, (c or "").replace("_", " ").capitalize())


def trend_svg(trend):
    n = len(trend)
    x0, x1, ybase, ytop, vmax = 60, 630, 190, 30, 60.0
    xs = [x0 + (x1 - x0) * i / max(n - 1, 1) for i in range(n)]
    y = lambda v: round(ybase - (ybase - ytop) * v / vmax, 1)
    a = [100 * t["p1"] / t["scored"] if t["scored"] else 0 for t in trend]
    b = [100 * t["p1_4"] / t["scored"] if t["scored"] else 0 for t in trend]
    pts = lambda vals: " ".join(f"{round(x)},{y(v)}" for x, v in zip(xs, vals))
    dots = "".join(f'<circle cx="{round(x)}" cy="{y(v)}" r="3"/>' for x, v in zip(xs, a))
    days = [dt.date.fromisoformat(t["d"][:10]) for t in trend]
    xl = "".join(f'<text x="{round(x)}" y="210">{d.month}/{d.day}</text>' for x, d in zip(xs, days))
    lbl = ""
    if n:
        for i in sorted({0, n - 1}):
            lbl += f'<text class="lbl" x="{round(xs[i])}" y="{y(a[i]) - 11}" text-anchor="middle">{round(a[i])}%</text>'
            lbl += f'<text x="{round(xs[i])}" y="{y(b[i]) + 15}" text-anchor="middle">{round(b[i])}%</text>'
    aria = (f"Daily page-1 rate from {days[0].month}/{days[0].day} to {days[-1].month}/{days[-1].day}: all six brands between "
            f"{round(min(a))} and {round(max(a))} percent, the original four brands between {round(min(b))} and {round(max(b))} percent") if n else "No trend data"
    return f"""<svg class="chart" viewBox="0 0 660 236" role="img" aria-label="{esc(aria)}">
      <g stroke="var(--line)" stroke-width="1">
        <line x1="40" x2="640" y1="190" y2="190"/><line x1="40" x2="640" y1="136.7" y2="136.7"/><line x1="40" x2="640" y1="83.3" y2="83.3"/><line x1="40" x2="640" y1="30" y2="30"/>
      </g>
      <g text-anchor="end"><text x="34" y="194">0%</text><text x="34" y="140.7">20%</text><text x="34" y="87.3">40%</text><text x="34" y="34">60%</text></g>
      <polyline fill="none" stroke="var(--green)" stroke-width="2.5" stroke-linejoin="round" points="{pts(a)}"/>
      <polyline fill="none" stroke="var(--grey)" stroke-width="2" stroke-dasharray="5 4" stroke-linejoin="round" points="{pts(b)}"/>
      <g fill="var(--green)">{dots}</g>
      {lbl}
      <g text-anchor="middle">{xl}</g>
    </svg>""", a, b


def render(m, template_head):
    ed = dt.date.fromisoformat(m["edition"][:10])
    captured, scored, p1 = m["captured"], m["scored"], m["doors_p1"]
    di = captured - scored
    carried = captured - m["read_today"]
    need = max(0, math.ceil(TARGET * scored) - p1)
    share = round(100 * m["skus_p1"] / m["slots"], 1) if m["slots"] else 0
    trend = m.get("trend") or []
    svg, ta, tb = trend_svg(trend)
    tdays = [dt.date.fromisoformat(t["d"][:10]) for t in trend]
    tscored = [t["scored"] for t in trend]
    dod = m.get("dod") or {"on": 0, "off": 0, "both": 0, "y": None, "t": None}
    dod_y = dt.date.fromisoformat(dod["y"][:10]) if dod.get("y") else None
    dod_t = dt.date.fromisoformat(dod["t"][:10]) if dod.get("t") else ed
    states = sorted(m.get("states") or [], key=lambda s: STATE_ORDER.index(s["state"]) if s["state"] in STATE_ORDER else 9)
    state_rows = "".join(
        f'<tr><td class="b">{esc(s["state"])}</td><td>{s["scored"]}</td><td>{s["p1"]}</td><td><div class="barwrap">'
        f'<div class="bar" style="width:{round(1.4 * pct(s["p1"], s["scored"]))}px"></div>{pct(s["p1"], s["scored"])}%</div></td>'
        f'<td>#{rk(s["avg_rank"])}</td></tr>' for s in states)
    rated = [s for s in states if s["scored"]]
    hi = max(rated, key=lambda s: s["p1"] / s["scored"]) if rated else None
    lo = min(rated, key=lambda s: s["p1"] / s["scored"]) if rated else None
    best_rank = min(rated, key=lambda s: float(s["avg_rank"] or 99)) if rated else None
    big = max(rated, key=lambda s: s["scored"]) if rated else None
    names = {"NY": "New York", "NJ": "New Jersey", "IL": "Illinois"}
    nm = lambda s: names.get(s["state"], s["state"])
    if hi and lo and best_rank and big:
        rank_clause = " and the best position" if best_rank is hi else f"; {nm(best_rank)} the best position"
        state_note = (f"{nm(hi)} has the highest page-1 rate{rank_clause}; {nm(lo)} the lowest rate. "
                      f"{nm(big)} carries {pct(big['scored'], scored)}% of the panel.")
    else:
        state_note = ""
    matrix = m.get("matrix") or []
    matrix_rows = "".join(
        f'<tr><td class="b">{esc(label_brand(r["brand_key"]))}</td><td>{esc(label_cat(r["category_canonical"]))}</td>'
        f'<td>{r["doors_p1"]}</td><td>{r["doors_r1"]}</td><td>#{rk(r["avg_rank"])}</td></tr>' for r in matrix)
    comps = m.get("competitors") or []
    cmax = comps[0]["n"] if comps else 1
    comp_rows = "".join(
        f'<div class="crow"><span>{esc(c["brand"])}</span><div class="cbar"><div style="width:{round(100 * c["n"] / cmax)}%"></div></div>'
        f'<span class="note">{c["n"]}</span></div>' for c in comps)
    sv_share = round(100 * m["sv_skus"] / m["vape_slots"], 1) if m["vape_slots"] else 0
    med = m["median_rank"]
    med = int(round(med)) if med is not None else "—"
    w = lambda n: round(100 * n / captured, 1) if captured else 0
    period = f"{fdate_short(tdays[0])} – {fdate_short(tdays[-1])}, read daily" if tdays else fdate_short(ed)
    dod_txt = (f"{fdate_short(dod_t)} vs. {fdate_short(dod_y)}, on the {dod['both']} doors read both days" if dod_y else "no prior day read")
    dod_kpi = (f"Doors onto / off page 1, {dod_t.strftime('%b %-d')} vs {dod_y.strftime('%b %-d')}, door by door." if dod_y else "No prior day read.")
    platforms = "Dutchie, Sweed, Carrot, JointCommerce, Jane"
    asof_pill = f"AS OF {fdate_long(ed).upper()} · DAILY EDITION"
    built = dt.datetime.fromisoformat(m["built_at"]) if m.get("built_at") else None
    built_txt = f"{built.strftime('%a %b %-d, %Y %H:%M')} CT" if built else "time not recorded"
    # The as-of line only states doors actually read on the audit date at build time
    # (read_today), never captured or carried doors, so it cannot overstate the read.
    asof_line = (f"Pre-certification read. Audit date {fdate_long(ed)}; edition built {built_txt}; "
                 f"{m['read_today']} of {m.get('panel', '—')} panel doors read on {fdate_short(ed)}. "
                 f"Figures are not yet certified and may change.")
    trend_note = (f"Read every day for {len(trend)} days; {min(tscored)}–{max(tscored)} doors scored per day. "
                  f"Each point is that day's own read. Holding the brand list constant, the six-brand rate ranged "
                  f"{round(min(ta))}–{round(max(ta))}% and the original four {round(min(tb))}–{round(max(tb))}% over the window.") if trend else ""
    body = f"""
<div class="wrap">

<header>
  <div class="top">
    <div class="kick">CURALEAF · PROJECT FIRST PAGE</div>
    <div class="pills"><a class="pill line" href="/curaleaf/outlets/" style="text-decoration:none">OUTLET VIEW →</a><div class="pill dark">PRE-CERTIFICATION READ</div><div class="pill line">{esc(asof_pill)}</div></div>
  </div>
  <h1>Project First Page — Weekly Scorecard</h1>
  <div class="meta">
    <div>Brands: <span>Anthem · Grassroots · FIND · Select · JAMS · B Noble</span></div>
    <div>Categories: <span>all</span></div>
    <div>States: <span>NY · NJ · IL</span></div>
    <div>Period: <span>{esc(period)}</span></div>
  </div>
  <div class="den" style="margin-bottom:8px"><b>As of:</b> {esc(asof_line)}</div>
  <div class="den"><b>Denominator:</b> {scored} independent dispensaries with a readable menu on a validated platform ({platforms}), of {captured} captured. Independent means no owner that grows or manufactures its own product, checked per door; doors that could not be determined are kept and disclosed. {di} Data Issue doors are excluded from every rate. Each door's most recent read is used ({m['read_today']} read on {fdate_short(ed)}, {carried} carried from the prior two days). This is <b>our panel, not your distribution file</b>: until the master file is joined, the KPI is <i>doors with a Curaleaf brand on page 1 ÷ doors scored</i>, not Page 1 Compliance as your guide defines it.</div>
</header>

<section class="panel">
  <div class="k">Your Pillar 1 KPIs against target · {esc(fdate_short(ed))}</div>
  <div class="grid" style="grid-template-columns:repeat(4,1fr);margin-top:14px">
    <div><div class="big" style="color:var(--green)">{pct(p1, scored)}%</div><div class="sub" style="font-weight:700">First-page rate · target ≥ 80%</div><div class="note">{p1} of {scored} doors. {need} more doors needed to reach target.</div></div>
    <div><div class="big">{pct(m['doors_top5'], scored)}%</div><div class="sub" style="font-weight:700">Top-position rate (1–5)</div><div class="note">{m['doors_top5']} doors with a Curaleaf brand in the top 5; {m['doors_r1']} at #1.</div></div>
    <div><div class="big">{share}%</div><div class="sub" style="font-weight:700">Share of menu</div><div class="note">Curaleaf share of all first-page slots; {m['avg_ahead']} competitor products ahead on average.</div></div>
    <div><div class="big"><span class="up">+{dod['on']}</span> / <span class="down">−{dod['off']}</span></div><div class="sub" style="font-weight:700">Position slippage &amp; recovery</div><div class="note">{esc(dod_kpi)}</div></div>
  </div>
  <p class="note" style="margin:12px 0 0">Category accuracy and content completeness: wrong-page listings and broken product titles are flagged daily; rates switch on with your SKU list. Menu presence needs your distribution file; volume lift needs sell-through from Insights.</p>
</section>

<section class="grid g2">
  <div class="panel hero">
    <div class="k">Curaleaf on page 1 — {esc(fdate_short(ed))}</div>
    <div class="row"><div class="v">{pct(p1, scored)}%</div><div class="side">{p1} of {scored} doors</div></div>
    <p>{p1} of {scored} scored independents show at least one Curaleaf brand on page 1 of at least one category, under the retailer's default sort.</p>
    <p><span class="up">▲ {dod['on']} doors moved onto page 1</span>&nbsp;&nbsp;<span class="down">▼ {dod['off']} fell off</span> <span class="note">{esc(dod_txt)}</span></p>
    <p class="note">{m['placements']} brand × category placements · {m['doors_r1']} doors with a Curaleaf brand at position 1 · {m['doors_top5']} with one in the top 5<br>Without Anthem and B Noble: {m['doors_p1_4']} doors ({pct(m['doors_p1_4'], scored)}%). Both brands are tracked across the full history shown.</p>
  </div>
  <div class="panel">
    <div class="k">Daily trend · share of scored doors on page 1</div>
    {svg}
    <div class="legend-inline"><span><span class="sw" style="background:var(--green)"></span>All six brands ({round(min(ta)) if ta else 0}–{round(max(ta)) if ta else 0}%)</span><span><span class="sw" style="background:var(--grey)"></span>Select · FIND · Grassroots · JAMS only</span></div>
    <p class="note" style="margin:8px 0 0">{esc(trend_note)}</p>
  </div>
</section>

<section class="grid g6">
  <div class="card"><div class="k">Avg first-product rank</div><div class="v">#{rk(m['avg_rank'])}</div><div class="sub">median #{med} on a {m['page_n_min']}–{m['page_n_max']} product page</div><div class="foot">Position within page 1, default sort</div></div>
  <div class="card locked"><div class="k">Critical gap rate</div><div class="v">—</div><div class="sub">Requires master file</div><div class="foot">Distributed and brand not found. Needs distribution status per door.</div></div>
  <div class="card locked"><div class="k">Assortment completion</div><div class="v">—</div><div class="sub">Requires master file</div><div class="foot">Expected SKUs live ÷ expected. Needs the expected SKU list per door.</div></div>
  <div class="card locked"><div class="k">Out-of-stock rate</div><div class="v">—</div><div class="sub">Requires master file</div><div class="foot">Needs expected SKUs; stock-state read switches on with the file.</div></div>
  <div class="card locked"><div class="k">Content accuracy</div><div class="v">—</div><div class="sub">Partly live</div><div class="foot">Product-name and wrong-page flags read daily; a rate needs your reference content.</div></div>
  <div class="card locked"><div class="k">Open exceptions &gt; 7 days</div><div class="v">—</div><div class="sub">Requires owner roster</div><div class="foot">Unresolved problems by owner. Needs the owner list.</div></div>
</section>

<section class="panel">
  <div class="k">Door status — all {captured} captured doors</div>
  <div class="status"><div style="width:{w(p1)}%;background:var(--green)"></div><div style="width:{w(scored - p1)}%;background:var(--neutral-bar)"></div><div style="width:{w(di)}%;background:var(--amber)"></div></div>
  <div class="legend">
    <div><i style="background:var(--green)"></i><b>On page 1 · {p1}</b><span class="note">At least one Curaleaf brand on page 1 of at least one category.</span></div>
    <div><i style="background:var(--neutral-bar)"></i><b>Not on page 1 · {scored - p1}</b><span class="note">Menu read cleanly, no Curaleaf brand on any page 1. Splits into Opportunity, Critical Gap and Not Expected once distribution is known.</span></div>
    <div><i style="background:var(--amber)"></i><b>Data issue · {di}</b><span class="note">Menu inaccessible or empty at capture. Excluded from rates.</span></div>
    <div><i style="background:var(--grey)"></i><b>Not scored here</b><span class="note">Dispense, Blaze and Flowhub storefronts are read for presence only; no validated page-1 rule yet.</span></div>
  </div>
</section>

<section class="grid g32">
  <div class="panel">
    <div class="k">Page 1 presence by state</div>
    <div class="tablewrap"><table style="margin-top:10px">
      <tr><th>STATE</th><th>DOORS SCORED</th><th>ON PAGE 1</th><th>PAGE 1 %</th><th>AVG RANK</th></tr>
      {state_rows}
    </table></div>
    <p class="note" style="margin:10px 0 0">{esc(state_note)}</p>
  </div>
  <div class="panel">
    <div class="k">Select · Vape — the pilot cut</div>
    <div class="pair"><div><div class="big" style="color:var(--green)">{pct(m['sv_p1'], m['sv_doors'])}%</div><div class="note">{m['sv_p1']} of {m['sv_doors']} doors with a vape page</div></div><div><div class="big">#{rk(m['sv_rank'])}</div><div class="note">avg first Select vape position</div></div></div>
    <p class="note" style="margin:12px 0 0">{m['sv_skus']} Select vape SKUs on page 1 across the panel, {sv_share}% of all first-page vape positions. Your guide's recommended pilot scope, read {esc(fdate_short(ed))}.</p>
  </div>
</section>

<section class="panel">
  <div class="k">Where each brand wins page 1</div>
  <div class="tablewrap"><table style="margin-top:10px">
    <tr><th>BRAND</th><th>CATEGORY</th><th>DOORS ON PAGE 1</th><th>AT POSITION 1</th><th>AVG RANK</th></tr>
    {matrix_rows}
  </table></div>
  <p class="note" style="margin:10px 0 0">Brand × category cells with 10 or more doors on page 1. B Noble is on page 1 at {m['b_noble_p1']} doors across categories.</p>
</section>

<section class="grid g2">
  <div class="panel">
    <div class="k">Competitive shelf pressure</div>
    <div class="pair"><div><div class="big" style="color:var(--green)">{m['avg_ahead']}</div><div class="note">avg competitor products ahead of the first Curaleaf SKU, where on page 1</div></div><div><div class="big">{share}%</div><div class="note">Curaleaf share of all first-page positions, all categories</div></div></div>
    <div style="margin-top:14px"><div class="note" style="margin-bottom:6px">Brands most often ahead of Curaleaf on page 1 (products ahead, {esc(fdate_short(ed))})</div>
      {comp_rows}
    </div>
  </div>
  <div class="panel">
    <div class="k">What this read does not include</div>
    <div class="tablewrap"><table style="margin-top:10px">
      <tr><th>GAP</th><th>WHY</th><th>CLOSES WHEN</th></tr>
      <tr><td class="b">Page 1 Compliance (your KPI)</td><td>No distribution status per door</td><td>Master file joined</td></tr>
      <tr><td class="b">Dispense, Blaze, Flowhub doors</td><td>Presence is read; page position is not yet validated</td><td>Page-1 rule validated per platform</td></tr>
      <tr><td class="b">Custom storefronts</td><td>No validated read route; excluded, not estimated</td><td>Route rebuild</td></tr>
      <tr><td class="b">Per-row screenshot evidence</td><td>Text read stores the products ahead, not the page image</td><td>Evidence store</td></tr>
    </table></div>
  </div>
</section>

<div class="defs"><b>DEFINITIONS —</b> <b>On page 1</b> = the brand's first product appears on the platform's own first page under the store's default sort (25 products on Dutchie, 24 on Jane, Sweed and Carrot, 20 on JointCommerce), recorded per row. <b>Independent</b> = no owner that holds a cultivation or manufacturing licence, checked per door; multi-store retailers are included. <b>Data issue</b> = menu inaccessible or empty at capture. <b>Day-over-day</b> = door-level change on doors read both days.<br>
<b>AUDIT STANDARD:</b> Store's default sort, no brand search, natural category navigation, the platform's actual first page. Text read from the storefront's own data layer. Every figure on this page reproduces from the stored daily shelf reads.</div>
<div class="foot2"><div><b>POWERED BY DOBBLES.AI</b> · DispensaryIQ · Verified, evidence-gated shelf observation.</div><div>Pre-certification daily edition for audit date {esc(fdate_long(ed))}, built {esc(built_txt)}. Published daily by 09:00 CT from the latest complete audit day.</div></div>

</div>
<!-- curaleaf-scorecard edition={ed.isoformat()} -->
</body></html>
"""
    return template_head + body


def split_head(page):
    """Everything up to and including </style> of the committed page: fonts, tokens, CSS."""
    i = page.find("</style>")
    if i < 0:
        raise RuntimeError("template page has no </style>")
    return page[: i + len("</style>")] + "\n"


def write_atomic(path, text):
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".curaleaf-", suffix=".html")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/curaleaf/index.html")
    ap.add_argument("--template", default=None, help="page whose <head>/CSS to reuse (default: --out)")
    ap.add_argument("--date", help="edition date YYYY-MM-DD (skips the short-day guard)")
    ap.add_argument("--print-sql", action="store_true")
    ap.add_argument("--from-json", help="render from a saved metrics JSON instead of querying")
    ap.add_argument("--watch", action="store_true",
                    help="cross-watch: DM Ed if the dip-service daily check has not run by 07:15 CT")
    ap.add_argument("--attempt", action="store_true",
                    help="cron publish attempt: no-op once today's edition is served; logs held/short attempts")
    a = ap.parse_args(argv)

    if a.print_sql:
        if not a.date:
            print(door_counts_sql())
        else:
            print(metrics_sql(dt.date.fromisoformat(a.date)))
        return 0

    if a.watch:
        dsn = os.environ.get("CURALEAF_SCORECARD_DSN") or os.environ.get("DIP_DATABASE_URL")
        if not dsn:
            log("watch: no CURALEAF_SCORECARD_DSN / DIP_DATABASE_URL")
            return 2
        log(f"watch: {watch(dsn)}")
        log(f"poller watch: {poller_watch(dsn)}")
        return 0

    lock = None
    try:
        if a.attempt:
            # boot render and cron attempts never run the render + email step at once
            lock = open(os.path.join(tempfile.gettempdir(), "curaleaf-publish.lock"), "w")
            fcntl.flock(lock, fcntl.LOCK_EX)
        dsn, live = None, None
        if a.from_json:
            with open(a.from_json) as f:
                m = json.load(f)
        else:
            dsn = os.environ.get("CURALEAF_SCORECARD_DSN") or os.environ.get("DIP_DATABASE_URL")
            if not dsn:
                log("no CURALEAF_SCORECARD_DSN / DIP_DATABASE_URL; leaving the current page as is")
                return 2
            if a.date:
                edition, why = dt.date.fromisoformat(a.date), "explicit --date"
            else:
                rows = neon_sql(dsn, door_counts_sql())
                today = dt.date.fromisoformat(rows[0]["ct_today"][:10])
                ct_hm = int(rows[0].get("ct_hm") or 0)
                if a.attempt and served_edition(a.out) == today:
                    log(f"today's edition {today} is already served; nothing to do")
                    return 0
                counts = [(r["d"], r["doors"]) for r in rows if r.get("d")]
                ratio = HARD_RATIO if ct_hm >= HARD_HM else SHORT_DAY_RATIO
                edition, why = pick_edition(counts, today, ratio)
                live = (today, ct_hm, why)
            log(f"edition {edition} ({why})")
            rows = neon_sql(dsn, metrics_sql(edition))
            m = rows[0]["m"]
            if isinstance(m, str):
                m = json.loads(m)
        if not m.get("scored"):
            raise RuntimeError("edition has zero scored doors; refusing to publish")
        with open(a.template or a.out, encoding="utf-8") as f:
            head = split_head(f.read())
        write_atomic(a.out, render(m, head))
        log(f"wrote {a.out} for edition {m['edition']}: {m['doors_p1']} of {m['scored']} doors on page 1")
        if live:
            after_render(dsn, m, live[0], live[1], a.attempt, live[2])
        return 0
    except Exception as e:  # leave the served page untouched on any failure
        log(f"ERROR {e!r}; current page left unchanged")
        return 1
    finally:
        if lock:
            lock.close()


if __name__ == "__main__":
    sys.exit(main())
