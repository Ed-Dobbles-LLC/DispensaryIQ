"""brief #5899 FIRST-PAGE-TRUTH-1: edition-day reads only, effective ownership, storefront
dedupe, and the auto re-render of today's served edition (scripts/curaleaf_scorecard.py)."""
import datetime as dt
import importlib.util
import json
import pathlib

_spec = importlib.util.spec_from_file_location(
    "curaleaf_scorecard", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "curaleaf_scorecard.py")
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)

ED = dt.date(2026, 10, 12)


def test_metrics_sql_reads_the_edition_day_only():
    q = cs.metrics_sql(ED)
    assert "FROM raw WHERE audit_date = date '2026-10-12')" in q
    assert "- 2 AND date" not in q
    assert "audit_ts <= date_trunc('minute', now())" in q


def test_panel_uses_effective_ownership_and_storefront_dedupe():
    q = cs.metrics_sql(ED)
    assert "ops.pfp_ownership_overrides" in q
    assert "dup1 AND verdict = 'RETAIL_ONLY' AS head" in q
    assert "verdict = 'CANNOT_DETERMINE'" in q          # 'undetermined' count for the as-of line
    assert r"substring(d.address::text from '^\s*(\d+)')" in q
    assert "<= 150)" in q
    # the address/name and dutchie menu dedupes are kept
    assert ") = 1 AS dup1" in q and "OR i.menu_ok)" in q and "AND i.head" in q


def test_served_built_marker(tmp_path):
    p = tmp_path / "index.html"
    p.write_text("<html><!-- curaleaf-scorecard edition=2026-10-12 built=2026-10-12T13:40:00Z -->\n</body></html>")
    assert cs.served_edition(str(p)) == ED
    assert cs.served_built(str(p)) == dt.datetime(2026, 10, 12, 13, 40, tzinfo=dt.timezone.utc)
    p.write_text("<html><!-- curaleaf-scorecard edition=2026-10-12 -->\n</body></html>")
    assert cs.served_edition(str(p)) == ED and cs.served_built(str(p)) is None


class FakeDB:
    def __init__(self, newer):
        self.newer, self.events, self.queries = newer, [], []

    def __call__(self, dsn, query, params=None):
        self.queries.append(query)
        if "AS ct_today" in query:
            return [{"ct_today": "2026-10-12", "ct_hm": "0910", "d": "2026-10-12", "doors": 500}]
        if "AS newer" in query:
            return [{"newer": self.newer, "max_ts": "2026-10-12T14:02:11Z"}]
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


def test_attempt_is_noop_when_no_newer_reads(tmp_path, monkeypatch):
    db = FakeDB(newer=False)
    monkeypatch.setattr(cs, "neon_sql", db)
    monkeypatch.setenv("CURALEAF_SCORECARD_DSN", "postgres://u:p@h/db")
    assert cs.main(["--out", str(_served(tmp_path)), "--attempt"]) == 0
    assert not any("json_build_object" in q for q in db.queries)


def test_attempt_rerenders_today_when_newer_reads(tmp_path, monkeypatch):
    db = FakeDB(newer=True)
    monkeypatch.setattr(cs, "neon_sql", db)
    monkeypatch.setenv("CURALEAF_SCORECARD_DSN", "postgres://u:p@h/db")
    cs.main(["--out", str(_served(tmp_path)), "--attempt"])
    metrics = [q for q in db.queries if "json_build_object" in q]
    assert len(metrics) == 1 and "audit_date = date '2026-10-12'" in metrics[0]


def test_render_states_exclusions_and_build_marker():
    m = {"edition": "2026-10-12", "built_at": "2026-10-12T09:10", "built_utc": "2026-10-12T14:10:00Z",
         "panel": 400, "undetermined": 117, "captured": 380, "scored": 370, "read_today": 380, "doors_p1": 200,
         "doors_p1_4": 150, "placements": 300, "doors_r1": 40, "doors_top5": 120, "avg_rank": 7.1,
         "median_rank": 6, "page_n_min": 20, "page_n_max": 25, "skus_p1": 500, "slots": 9000,
         "avg_ahead": 5.0, "states": [{"state": "NY", "scored": 200, "p1": 110, "avg_rank": 6.5},
                                      {"state": "NJ", "scored": 170, "p1": 90, "avg_rank": 7.5}],
         "matrix": [], "b_noble_p1": 3, "sv_doors": 50, "sv_p1": 20, "sv_rank": 8, "sv_skus": 30,
         "vape_slots": 1200, "competitors": [], "trend": [{"d": "2026-10-11", "scored": 360, "p1": 190, "p1_4": 140},
                                                         {"d": "2026-10-12", "scored": 370, "p1": 200, "p1_4": 150}],
         "dod": None}
    page = cs.render(m, "<html><style></style>\n")
    assert "117 further panel doors excluded because their ownership is not confirmed" in page
    assert "Only reads taken on" in page and "carried" not in page
    assert "edition=2026-10-12 built=2026-10-12T14:10:00Z -->" in page
