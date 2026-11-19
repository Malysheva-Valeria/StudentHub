import pytest

from app.csv_export import to_csv
from app.grading import attendance_rate, to_ects


@pytest.mark.parametrize("score,letter", [
    (100, "A"), (90, "A"), (89.5, "A"), (89.4, "B"), (82, "B"), (81, "C"), (74, "C"), (73, "D"),
    (64, "D"), (63, "E"), (60, "E"), (59, "FX"), (35, "FX"), (34, "F"), (0, "F"),
])
def test_ects_boundaries(score, letter):
    assert to_ects(score)["ects"] == letter


def test_ects_misc():
    assert to_ects(None) is None
    assert to_ects(95)["national"] == "Відмінно"


def test_attendance_rate():
    assert attendance_rate(8, 1, 10) == 90
    assert attendance_rate(0, 0, 0) is None
    assert attendance_rate(2, 0, 3) == 66.7


def test_csv_escaping_and_formula_injection():
    csv = to_csv([{"a": "x;y", "b": "=SUM(A1)", "c": 'he said "hi"', "d": -5}], [("a", "A"), ("b", "B"), ("c", "C"), ("d", "D")])
    assert csv.startswith("﻿")
    assert csv.split("\r\n")[1] == "\"x;y\";'=SUM(A1);\"he said \"\"hi\"\"\";-5"


def test_dashboard_consistency(admin, db):
    d = admin.get("/api/dashboard").json()
    k = d["kpi"]
    assert k["total_students"] == db.execute("SELECT COUNT(*) AS c FROM students").fetchone()["c"]
    assert d["gender"]["male"] + d["gender"]["female"] == k["active_students"]
    assert 0 < len(d["trend"]) <= 6 and all(0 <= t["rate"] <= 100 for t in d["trend"])
    assert sum(d["distribution"].values()) > 0
    assert len(d["by_group"]) == k["groups"]
    # mean of active students' averages, same as the performance report summary
    assert k["avg_grade"] == admin.get("/api/reports/performance").json()["summary"]["avg_grade"]


def test_performance_report(admin):
    r = admin.get("/api/reports/performance?group_id=1").json()
    items, s = r["items"], r["summary"]
    assert items and all(i["group_name"] == "КН-11" for i in items)
    assert s["students"] == len(items)
    graded = [i for i in items if i["avg_grade"] is not None]
    assert s["excellent"] + s["good"] + s["satisfactory"] + s["failing"] == len(graded)
    for i in graded:
        assert i["ects"] == to_ects(i["avg_grade"])["ects"]


def test_performance_period_filter(admin, db):
    r = admin.get("/api/reports/performance?subject_id=1&from=2026-10-01&to=2026-10-31").json()
    row = next(i for i in r["items"] if i["grades_count"] > 0)
    raw = db.execute("SELECT COUNT(*) AS c FROM grades WHERE student_id=? AND subject_id=1 AND date BETWEEN '2026-10-01' AND '2026-10-31'",
                     (row["student_id"],)).fetchone()["c"]
    assert row["grades_count"] == raw


def test_attendance_report(admin):
    r = admin.get("/api/reports/attendance?group_id=2").json()
    s, items = r["summary"], r["items"]
    assert s["total"] == sum(i["total"] for i in items)
    assert s["present"] + s["late"] + s["absent"] + s["excused"] == s["total"]
    assert s["low"] == sum(1 for i in items if i["rate"] is not None and i["rate"] < 75)


def test_groups_report_and_csv(admin, db):
    assert len(admin.get("/api/reports/groups").json()) == db.execute("SELECT COUNT(*) AS c FROM groups").fetchone()["c"]
    for name in ("performance", "attendance", "groups"):
        r = admin.get(f"/api/reports/{name}?format=csv")
        assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
        assert len(r.content.decode("utf-8-sig").split("\r\n")) > 2
