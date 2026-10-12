"""brief #5902 FIRST-PAGE-LIVE-1: auto re-render of today's served edition when newer reads land,
and the edition-day-only switch (ops.firstpage_config, ships false) in scripts/curaleaf_scorecard.py."""
import datetime as dt
import importlib.util
import json
import pathlib

_spec = importlib.util.spec_from_file_location(
    "curaleaf_scorecard", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "curaleaf_scorecard.py")
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)

ED = dt.date(2026, 10, 12)


def test_metrics_sql_switch_off_keeps_the_three_day_window():
    q = cs.metrics_sql(ED)
    assert "FROM raw WHERE audit_date BETWEEN date '2026-10-12' - 2 AND date '2026-10-12')" in q
    assert "'edition_day_only', false" in q


def test_metrics_sql_switch_on_reads_the_edition_day_only():
    q = cs.metrics_sql(ED, edition_day_only=True)
    assert "FROM raw WHERE audit_date BETWEEN date '2026-10-12' AND date '2026-10-12')" in q
    assert "'edition_day_only', true" in q


def test_panel_definition_unchanged_only_planner_shape():
    q = cs.metrics_sql(ED)
    # same ownership universe as dsps.v_firstpage_scorecard_latest: base table, RO + CD kept
    assert "o.verdict IN ('RETAIL_ONLY', 'CANNOT_DETERMINE')" in q
    assert "pfp_ownership_overrides" not in q
    # dedupes kept, as boolean flags
    assert ") = 1 AS dup1" in q and ") = 1 AS menu_ok" in q and "AND i.dup1" in q and "OR i.menu_ok)" in q
    assert "audit_ts <= date_trunc('minute', now())" in q


def test_served_built_marker(tmp_path):
    p = tmp_path / "index.html"
    p.write_text("<html><!-- curaleaf-scorecard edition=2026-10-12 built=2026-10-12T13:40:00Z -->\n</body></html>")
    assert cs.served_edition(str(p)) == ED
    assert cs.served_built(str(p)) == dt.datetime(2026, 10, 12, 13, 40, tzinfo=dt.timezone.utc)
    p.write_text("<html><!-- curaleaf-scorecard edition=2026-10-12 -->\n</body></html>")
    assert cs.served_edition(str(p)) == ED and cs.served_built(str(p)) is None


class FakeDB:
    def __init__(self, newer, config=None, config_error=False):
        self.newer, self.config, self.config_error = newer, config, config_error
        self.events, self.queries = [], []

    def __call__(self, dsn, query, params=None):
        self.queries.append(query)
        if "AS ct_today" in query:
            return [{"ct_today": "2026-10-12", "ct_hm": "0910", "d": "2026-10-12", "doors": 500}]
        if "AS newer" in query:
            return [{"newer": self.newer, "max_ts": "2026-10-12T14:02:11Z"}]
        if "ops.firstpage_config" in query:
            if self.config_error:
                raise RuntimeError('relation "ops.firstpage_config" does not exist')
            return [] if self.config is None else [{"value": self.config}]
        if "json_build_object" in query:
            return [{"m": {"edition": "2026-10-12", "scored": 0}}]   # zero scored: refuses to write
        if query.startswith("INSERT INTO ops.curaleaf_publish_events"):
            self.events.append((params[0], json.loads(params[1])))
            return []
        raise AssertionError(query)


def _served(tmp_path):
    p = tmp_path / "index.html"
    p.write_text("<style></style><!-- curaleaf-scorecard edition=2026-10-12 built=2026-10-12T13:40:00Z -->")
    return p


def _run(tmp_path, monkeypatch, db):
    monkeypatch.setattr(cs, "neon_sql", db)
    monkeypatch.setenv("CURALEAF_SCORECARD_DSN", "postgres://u:p@h/db")
    return cs.main(["--out", str(_served(tmp_path)), "--attempt"])


def test_attempt_is_noop_when_no_newer_reads(tmp_path, monkeypatch):
    db = FakeDB(newer=False)
    assert _run(tmp_path, monkeypatch, db) == 0
    assert not any("json_build_object" in q for q in db.queries)


def test_attempt_rerenders_today_when_newer_reads(tmp_path, monkeypatch):
    db = FakeDB(newer=True, config=False)
    _run(tmp_path, monkeypatch, db)
    metrics = [q for q in db.queries if "json_build_object" in q]
    assert len(metrics) == 1 and "audit_date BETWEEN date '2026-10-12' - 2 AND date '2026-10-12'" in metrics[0]


def test_switch_on_is_read_from_config(tmp_path, monkeypatch):
    db = FakeDB(newer=True, config=True)
    _run(tmp_path, monkeypatch, db)
    metrics = [q for q in db.queries if "json_build_object" in q]
    assert "audit_date BETWEEN date '2026-10-12' AND date '2026-10-12'" in metrics[0]


def test_missing_config_table_reads_as_off(tmp_path, monkeypatch):
    db = FakeDB(newer=True, config_error=True)
    _run(tmp_path, monkeypatch, db)
    metrics = [q for q in db.queries if "json_build_object" in q]
    assert "audit_date BETWEEN date '2026-10-12' - 2 AND date '2026-10-12'" in metrics[0]


def _m(**kw):
    m = {"edition": "2026-10-12", "built_at": "2026-10-12T09:10", "built_utc": "2026-10-12T14:10:00Z",
         "panel": 514, "captured": 380, "scored": 370, "read_today": 360, "doors_p1": 200,
         "doors_p1_4": 150, "placements": 300, "doors_r1": 40, "doors_top5": 120, "avg_rank": 7.1,
         "median_rank": 6, "page_n_min": 20, "page_n_max": 25, "skus_p1": 500, "slots": 9000,
         "avg_ahead": 5.0, "states": [{"state": "NY", "scored": 200, "p1": 110, "avg_rank": 6.5},
                                      {"state": "NJ", "scored": 170, "p1": 90, "avg_rank": 7.5}],
         "matrix": [], "b_noble_p1": 3, "sv_doors": 50, "sv_p1": 20, "sv_rank": 8, "sv_skus": 30,
         "vape_slots": 1200, "competitors": [], "trend": [{"d": "2026-10-11", "scored": 360, "p1": 190, "p1_4": 140},
                                                         {"d": "2026-10-12", "scored": 370, "p1": 200, "p1_4": 150}],
         "dod": None}
    m.update(kw)
    return m


def test_render_switch_off_discloses_carry_forward_and_marks_build():
    page = cs.render(_m(edition_day_only=False), "<html><style></style>\n")
    assert "20 carried from the prior two days" in page and "today's reads only" not in page
    assert "edition=2026-10-12 built=2026-10-12T14:10:00Z -->" in page


def test_render_switch_on_says_todays_reads_only():
    page = cs.render(_m(edition_day_only=True, captured=360), "<html><style></style>\n")
    assert "today&#x27;s reads only" in page or "today's reads only" in page
    assert "Only reads taken on" in page and "carried from the prior two days" not in page
