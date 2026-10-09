"""brief #5807: 09:00 CT hard publish + email on publish (scripts/curaleaf_scorecard.py)."""
import datetime as dt
import importlib.util
import json
import pathlib

_spec = importlib.util.spec_from_file_location(
    "curaleaf_scorecard", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "curaleaf_scorecard.py")
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)

TODAY = dt.date(2026, 10, 9)
# today 80 doors, prior 7 dates 100 each
COUNTS = [("2026-10-09", 80)] + [(f"2026-10-0{d}", 100) for d in range(8, 1, -1)]
M = {"edition": "2026-10-09", "read_today": 412, "panel": 520, "doors_p1": 131, "scored": 455}


class FakeDB:
    def __init__(self, subs=("ed@dobbles.ai",)):
        self.events, self.subs = [], list(subs)

    def __call__(self, dsn, query, params=None):
        if query.startswith("INSERT INTO ops.curaleaf_publish_events"):
            self.events.append((params[0], json.loads(params[1])))
            return []
        if "FROM ops.curaleaf_subscribers" in query:
            return [{"email": e} for e in self.subs]
        if "count(*)" in query and "curaleaf_publish_events" in query:
            kind, ed = params[0], params[1]
            n = sum(1 for k, d in self.events if k == kind and d.get("edition") == ed
                    and (len(params) < 3 or d.get("email") == params[2]))
            return [{"n": n}]
        raise AssertionError(query)


class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, u, p):
        pass

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def test_short_today_holds_before_0845_and_publishes_at_75pct_after():
    assert cs.pick_edition(COUNTS, TODAY)[0] == dt.date(2026, 10, 8)
    assert cs.pick_edition(COUNTS, TODAY, cs.HARD_RATIO)[0] == TODAY
    low = [("2026-10-09", 70)] + COUNTS[1:]
    assert cs.pick_edition(low, TODAY, cs.HARD_RATIO)[0] == dt.date(2026, 10, 8)


def test_publish_logs_event_and_skips_email_without_credentials(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(cs, "neon_sql", db)
    for v in ("SCORECARD_SMTP_HOST", "SCORECARD_SMTP_USER", "SCORECARD_SMTP_PASSWORD", "CURALEAF_EMAIL_DISABLED"):
        monkeypatch.delenv(v, raising=False)
    cs.after_render("dsn", M, TODAY, 712, True, "ok")
    cs.after_render("dsn", M, TODAY, 722, False, "ok")  # boot re-render: idempotent
    kinds = [k for k, _ in db.events]
    assert kinds == ["published", "email_skipped_no_credentials"]
    assert db.events[0][1]["doors_read"] == 412 and db.events[0][1]["p1_denom"] == 455


def test_email_once_per_edition_to_approved_only(monkeypatch):
    db = FakeDB(subs=("ed@dobbles.ai",))
    monkeypatch.setattr(cs, "neon_sql", db)
    monkeypatch.setenv("SCORECARD_SMTP_HOST", "smtp.example")
    monkeypatch.setenv("SCORECARD_SMTP_USER", "u")
    monkeypatch.setenv("SCORECARD_SMTP_PASSWORD", "p")
    monkeypatch.delenv("CURALEAF_EMAIL_DISABLED", raising=False)
    FakeSMTP.sent = []
    assert cs.send_publish_emails("dsn", M, smtp_factory=FakeSMTP) == "sent 1 of 1"
    assert cs.send_publish_emails("dsn", M, smtp_factory=FakeSMTP) == "nothing to send"
    assert len(FakeSMTP.sent) == 1
    msg = FakeSMTP.sent[0]
    assert msg["Subject"] == "Curaleaf First Page - Friday Oct 9 edition is live"
    assert (msg["From"].addresses[0].display_name, msg["From"].addresses[0].addr_spec) == \
        ("DispensaryIntelligence", "ed@dispensaryintelligence.com")
    body = msg.get_body(("plain",)).get_content()
    assert "412 of 520 panel doors read" in body and "Page 1 at 131 of 455 doors" in body


def test_prior_edition_never_emails_and_records_held(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(cs, "neon_sql", db)
    prior = dict(M, edition="2026-10-08")
    cs.after_render("dsn", prior, TODAY, 650, True, "short")
    cs.after_render("dsn", prior, TODAY, 845, True, "short")
    cs.after_render("dsn", prior, TODAY, 900, False, "boot")  # boot render of a prior edition logs nothing
    assert [k for k, _ in db.events] == ["attempt_short", "held"]


def test_served_edition_marker(tmp_path):
    p = tmp_path / "index.html"
    p.write_text("<html>...<!-- curaleaf-scorecard edition=2026-10-09 -->\n</body></html>")
    assert cs.served_edition(str(p)) == TODAY
    assert cs.served_edition(str(tmp_path / "missing.html")) is None
