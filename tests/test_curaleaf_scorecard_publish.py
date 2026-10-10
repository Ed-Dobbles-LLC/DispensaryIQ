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


# ---- brief #5851: cross-watch of the dip-service daily check ----

def _watch_row(hm, checks=0, alerted=0):
    return lambda dsn, q, params=None: [{"ct_hm": hm, "ct_today": "2026-10-11", "checks": checks, "alerted": alerted}]


def test_watch_quiet_before_0715_and_when_check_ran(monkeypatch):
    sent = []
    dm = lambda dsn, text: sent.append(text) or "sent (ts=1)"
    assert cs.watch("dsn", sql=_watch_row(710), dm=dm) == "before 07:15 CT"
    assert cs.watch("dsn", sql=_watch_row(720, checks=9), dm=dm).startswith("ok")
    assert cs.watch("dsn", sql=_watch_row(720, alerted=1), dm=dm) == "missing; already alerted today"
    assert sent == []


def test_watch_alerts_once_and_logs(monkeypatch):
    logged = []
    monkeypatch.setattr(cs, "log_event", lambda dsn, kind, detail: logged.append((kind, detail)))
    sent = []
    texts = []
    out = cs.watch("dsn", sql=_watch_row(720), dm=lambda dsn, text: sent.append(text) or "sent (ts=1)",
                   text_ed=lambda dsn, key, body: texts.append((key, body)) or "queued id=5")
    assert out == "missing; alert sent (ts=1); imessage queued id=5"
    assert sent[0].startswith("First Page check has not run today")
    assert texts == [("check_missing:2026-10-11:07:15",
                      "First Page check NOT RUN 10/11 - dip-service tick may be down (DispensaryIQ cross-watch)")]
    assert logged[0][0] == "check_missing_alert" and logged[0][1]["dm"] == "sent (ts=1)"
    assert logged[0][1]["imessage"] == "queued id=5"


# ---- brief #5852: Mac iMessage poller heartbeat ----

def _poller_row(hm, age, alerted=0):
    return lambda dsn, q, params=None: [{"ct_hm": hm, "ct_today": "2026-10-11", "age_min": age, "alerted": alerted}]


def test_poller_watch_quiet_cases():
    dm = lambda d, t: (_ for _ in ()).throw(AssertionError("no DM expected"))
    assert cs.poller_watch("dsn", sql=_poller_row(430, None), dm=dm) == "outside 05:00-10:00 CT"
    assert cs.poller_watch("dsn", sql=_poller_row(1005, None), dm=dm) == "outside 05:00-10:00 CT"
    assert cs.poller_watch("dsn", sql=_poller_row(600, 1), dm=dm) == "ok: heartbeat 1 min ago"
    assert cs.poller_watch("dsn", sql=_poller_row(600, 45, alerted=1), dm=dm) == "stale; already alerted today"


def test_poller_watch_alerts_on_stale_or_missing(monkeypatch):
    logged = []
    monkeypatch.setattr(cs, "log_event", lambda dsn, kind, detail: logged.append((kind, detail)))
    sent = []
    dm = lambda d, t: sent.append(t) or "sent (ts=2)"
    assert cs.poller_watch("dsn", sql=_poller_row(615, 21), dm=dm) == "stale; alert sent (ts=2)"
    assert cs.poller_watch("dsn", sql=_poller_row(615, None), dm=dm) == "stale; alert sent (ts=2)"
    assert "last heartbeat 21 min ago" in sent[0] and "last heartbeat never" in sent[1]
    assert [k for k, _ in logged] == ["poller_dead_alert", "poller_dead_alert"]


def test_enqueue_text_never_raises(monkeypatch):
    monkeypatch.setattr(cs, "neon_sql", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert cs.enqueue_text("dsn", "k", "b") == "failed: RuntimeError"
    monkeypatch.setattr(cs, "neon_sql", lambda *a, **k: [{"id": None}])
    assert cs.enqueue_text("dsn", "k", "b").startswith("not queued")
    monkeypatch.setattr(cs, "neon_sql", lambda *a, **k: [{"id": 9}])
    assert cs.enqueue_text("dsn", "k", "b") == "queued id=9"


def test_watch_kill_switch(monkeypatch):
    monkeypatch.setenv("CURALEAF_WATCH_DISABLED", "1")
    assert cs.watch("dsn", sql=_watch_row(720), dm=lambda d, t: "x") == "disabled"


def test_slack_dm_skips_without_creds(monkeypatch):
    monkeypatch.setattr(cs, "neon_sql", lambda dsn, q, params=None: [{"slack_token": None, "slack_channel": None}])
    assert cs.slack_dm("dsn", "x").startswith("skipped")
