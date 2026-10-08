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

Usage:
    python3 scripts/curaleaf_scorecard.py --out site/curaleaf/index.html          # live (Neon HTTP SQL)
    python3 scripts/curaleaf_scorecard.py --print-sql --date 2026-10-07           # emit the metrics SQL
    python3 scripts/curaleaf_scorecard.py --from-json m.json --out index.html     # render saved metrics

Env: CURALEAF_SCORECARD_DSN (falls back to DIP_DATABASE_URL). Stdlib only.
Exit codes: 0 rendered (or kept the previous edition on a short day), 2 no DSN, 1 error.
On any error the existing page is left untouched.
"""

import argparse
import datetime as dt
import html
import json
import math
import os
import sys
import tempfile
import urllib.request

SHORT_DAY_RATIO = 0.90
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
SELECT {CT_TODAY_SQL}::text AS ct_today, c.d, c.doors
FROM (SELECT 1) one LEFT JOIN (SELECT audit_date::text AS d, count(DISTINCT dispensary_id) AS doors FROM raw GROUP BY 1) c ON true
ORDER BY c.d DESC"""


def pick_edition(counts, ct_today):
    """counts: [(date_str, doors)] newest first. Returns (edition_date, reason)."""
    counts = [(dt.date.fromisoformat(d[:10]), int(n)) for d, n in counts]
    counts = [c for c in counts if c[0] <= ct_today]
    for i, (d, n) in enumerate(counts):
        prior = [m for _, m in counts[i + 1:i + 8]]
        avg = sum(prior) / len(prior) if prior else 0
        if not prior or n >= SHORT_DAY_RATIO * avg:
            return d, (f"{d}: {n} doors vs 7-date avg {avg:.0f}" if prior else f"{d}: no prior history")
        log(f"short day {d}: {n} doors < {SHORT_DAY_RATIO:.0%} of 7-date avg {avg:.0f}; keeping previous day's edition")
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


def neon_sql(dsn, query):
    host = dsn.split("@")[1].split("/")[0].split(":")[0]
    req = urllib.request.Request(
        f"https://{host}/sql", data=json.dumps({"query": query}).encode(),
        headers={"Content-Type": "application/json", "Neon-Connection-String": dsn},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r).get("rows", [])


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
<div class="foot2"><div><b>POWERED BY DOBBLES.AI</b> · DispensaryIQ · Verified, evidence-gated shelf observation.</div><div>Pre-certification daily edition for audit date {esc(fdate_long(ed))}, built {esc(built_txt)}. Published daily at 07:00 CT from the latest complete audit day.</div></div>

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
    a = ap.parse_args(argv)

    if a.print_sql:
        if not a.date:
            print(door_counts_sql())
        else:
            print(metrics_sql(dt.date.fromisoformat(a.date)))
        return 0

    try:
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
                counts = [(r["d"], r["doors"]) for r in rows if r.get("d")]
                edition, why = pick_edition(counts, today)
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
        return 0
    except Exception as e:  # leave the served page untouched on any failure
        log(f"ERROR {e!r}; current page left unchanged")
        return 1


if __name__ == "__main__":
    sys.exit(main())
