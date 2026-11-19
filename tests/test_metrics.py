"""Metrics match across the dashboard, groups page and reports."""
from app.utils import local_today
from datetime import timedelta

import pytest

from app.csv_export import to_csv
from app.grading import avg1, bucket, round1, round_half_up

D = [(local_today() - timedelta(days=n)).isoformat() for n in range(30)]  # D[0] is today


@pytest.fixture(scope="module")
def lab(admin, db):
    """Group with known grades: retakes, the 73.5 boundary, an expelled student."""
    teacher_id = db.execute("SELECT id FROM users WHERE username = 'teacher'").fetchone()["id"]
    g = admin.post("/api/groups", json={"name": "MET-1", "course": 6, "specialty": "x"}).json()
    subj = admin.post("/api/subjects", json={"name": "Метрики", "credits": 3, "hours": 90, "semester": 1,
                                             "control": "exam", "teacher_id": teacher_id, "group_ids": [g["id"]]}).json()
    ids = {}
    for key in ("retake_ok", "retake_fail", "border", "gone"):
        r = admin.post("/api/students", json={"last_name": "Метрик", "first_name": key, "gender": "F",
                                              "record_book": f"MET-{key}", "group_id": g["id"], "enrolled_at": "2024-09-01"})
        ids[key] = r.json()["id"]

    def put(student, value, type_, day):
        r = admin.post("/api/grades", json={"student_id": ids[student], "subject_id": subj["id"], "value": value,
                                            "type": type_, "date": day})
        assert r.status_code == 201, r.text

    put("retake_ok", 40, "exam", D[10]); put("retake_ok", 75, "exam", D[5])       # retake cleared the debt
    put("retake_fail", 75, "exam", D[10]); put("retake_fail", 40, "exam", D[5])   # latest final grade is 40
    put("border", 73, "current", D[3]); put("border", 74, "module", D[2])         # average 73.5
    put("gone", 100, "current", D[20])                                             # date unique to this student
    admin.patch(f"/api/students/{ids['gone']}", json={"status": "expelled"})
    for student, status in (("retake_ok", "present"), ("retake_fail", "late"), ("border", "absent")):
        admin.post("/api/attendance/bulk", json={"subject_id": subj["id"], "date": D[4],
                                                 "records": [{"student_id": ids[student], "status": status}]})
    return {"group": g["id"], "subject": subj["id"], **ids}


def test_rounding_helpers():
    assert round_half_up(73.5) == 74 and round_half_up(89.5) == 90 and round_half_up(0.5) == 1
    assert round1(73.45) == 73.5 and round1(66.66666) == 66.7 and round1(None) is None
    assert avg1([73, 74]) == 73.5 and avg1([]) is None
    assert avg1([0.1] * 10) == avg1(list(reversed([0.1] * 10))) == 0.1


@pytest.mark.parametrize("score,expected", [
    (90, "excellent"), (89.5, "excellent"), (89.4, "good"), (74, "good"), (73.5, "good"), (73.4, "satisfactory"),
    (60, "satisfactory"), (59.5, "satisfactory"), (59.4, "failing"), (0, "failing"), (None, None),
])
def test_bucket_follows_ects_letter(score, expected):
    assert bucket(score) == expected


def test_debts_and_retake(admin, lab):
    rep = admin.get(f"/api/reports/performance?group_id={lab['group']}").json()
    by_id = {i["student_id"]: i for i in rep["items"]}
    assert by_id[lab["retake_ok"]]["debts"] == 0
    assert by_id[lab["retake_fail"]]["debts"] == 1
    assert rep["summary"]["with_debts"] == 1
    card = admin.get(f"/api/students/{lab['retake_ok']}").json()
    subj = next(s for s in card["subjects"] if s["id"] == lab["subject"])
    assert subj["final_grade"] == 75 and subj["debt"] is False and subj["ects"]["ects"] == "C"
    card = admin.get(f"/api/students/{lab['retake_fail']}").json()
    subj = next(s for s in card["subjects"] if s["id"] == lab["subject"])
    assert subj["final_grade"] == 40 and subj["debt"] is True


def test_bucket_consistency_at_73_5(admin, lab):
    rep = admin.get(f"/api/reports/performance?group_id={lab['group']}").json()
    row = next(i for i in rep["items"] if i["student_id"] == lab["border"])
    assert row["avg_grade"] == 73.5 and row["ects"] == "C" and row["national"] == "Добре"
    s = rep["summary"]
    # retake_ok: (40+75)/2=57.5 → FX; retake_fail: 57.5 → FX; border: 73.5 → C
    assert (s["excellent"], s["good"], s["satisfactory"], s["failing"]) == (0, 1, 0, 2)
    assert s["quality"] == 33.3 and s["success"] == 33.3


def test_group_average_ignores_inactive_students(admin, lab):
    g = admin.get(f"/api/groups/{lab['group']}").json()
    assert g["avg_grade"] == avg1([57.5, 57.5, 73.5]) == 62.8, "оцінка 100 відрахованого студента не враховується"
    assert g["students_count"] == 3


def test_group_average_same_on_all_pages(admin):
    groups = {g["id"]: g["avg_grade"] for g in admin.get("/api/groups").json()}
    dash = {g["id"]: g for g in admin.get("/api/dashboard").json()["by_group"]}
    report = {g["id"]: g for g in admin.get("/api/reports/groups").json()}
    assert groups.keys() == dash.keys() == report.keys()
    for gid, avg in groups.items():
        assert dash[gid]["avg_grade"] == report[gid]["avg_grade"] == avg, gid
        assert admin.get(f"/api/reports/performance?group_id={gid}").json()["summary"]["avg_grade"] == avg, gid
        assert dash[gid]["attendance_rate"] == report[gid]["attendance_rate"], gid
        assert admin.get(f"/api/reports/attendance?group_id={gid}").json()["summary"]["rate"] == report[gid]["attendance_rate"]


def test_dashboard_matches_reports(admin):
    k = admin.get("/api/dashboard").json()["kpi"]
    perf = admin.get("/api/reports/performance").json()["summary"]
    att = admin.get("/api/reports/attendance").json()["summary"]
    assert k["avg_grade"] == perf["avg_grade"]
    assert k["success_rate"] == perf["success"]
    assert k["attendance_rate"] == att["rate"]
    assert k["low_attendance"] == att["low"]


def test_attendance_rate_same_in_list_card_and_report(admin, lab):
    sid = lab["retake_fail"]
    listed = next(s for s in admin.get(f"/api/students?group_id={lab['group']}").json()["items"] if s["id"] == sid)
    card = admin.get(f"/api/students/{sid}").json()
    report = next(i for i in admin.get(f"/api/reports/attendance?group_id={lab['group']}").json()["items"] if i["student_id"] == sid)
    assert listed["attendance_rate"] == card["attendance"]["rate"] == report["rate"] == 100.0


def test_journal_ignores_expelled_students(admin, lab):
    j = admin.get(f"/api/grades/journal?group_id={lab['group']}&subject_id={lab['subject']}").json()
    assert f"{D[20]}|current" not in {c["key"] for c in j["columns"]}
    assert lab["gone"] not in {r["id"] for r in j["rows"]}


def test_dashboard_trend(admin):
    d = admin.get("/api/dashboard").json()
    assert 0 < len(d["trend"]) <= 6
    months = [t["month"] for t in d["trend"]]
    assert months == sorted(months)
    assert d["kpi"]["academic_year_start"].endswith("-09-01")
    perf = admin.get("/api/reports/performance").json()["summary"]
    assert sum(d["distribution"].values()) == perf["excellent"] + perf["good"] + perf["satisfactory"] + perf["failing"]


# ---------- Sorting and search ----------
def test_collate_uk_in_catalog_lists(admin):
    for name in ("Єдність тест", "Абетка тест"):
        admin.post("/api/subjects", json={"name": name, "credits": 1, "hours": 10, "semester": 12, "control": "credit"})
    names = [s["name"] for s in admin.get("/api/subjects").json() if s["name"].endswith(" тест")]
    assert names == ["Абетка тест", "Єдність тест"]
    for name in ("ЄА-61", "АБ-61"):
        admin.post("/api/groups", json={"name": name, "course": 6, "specialty": "x"})
    names = [g["name"] for g in admin.get("/api/groups").json() if g["name"] in ("ЄА-61", "АБ-61")]
    assert names == ["АБ-61", "ЄА-61"]
    for login_, full in (("yermak", "Єрмак Іван"), ("andr", "Андрієнко Іван")):
        admin.post("/api/users", json={"username": login_, "password": "secret1", "full_name": full, "role": "teacher"})
    names = [u["full_name"] for u in admin.get("/api/users").json() if u["full_name"] in ("Єрмак Іван", "Андрієнко Іван")]
    assert names == ["Андрієнко Іван", "Єрмак Іван"]
    brief = [u["full_name"] for u in admin.get("/api/users/teachers").json() if u["full_name"] in ("Єрмак Іван", "Андрієнко Іван")]
    assert brief == names


@pytest.mark.parametrize("query", ["мар'ян", "марʼян", "мар’ян", "мар`ян", "МАР'ЯН"])
def test_search_normalises_apostrophes(admin, query):
    if not admin.get("/api/students", params={"search": "Мар’яненко"}).json()["total"]:
        admin.post("/api/students", json={"last_name": "Мар’яненко", "first_name": "Ія", "gender": "F", "record_book": "APO-1"})
    items = admin.get("/api/students", params={"search": query}).json()["items"]
    assert [s["last_name"] for s in items] == ["Мар’яненко"]


# ---------- CSV ----------
def test_csv_decimal_comma_and_phone():
    csv = to_csv([{"a": 73.5, "b": "+380 (67) 111-22-33", "c": "-1+1", "d": "=1+1", "e": 5}],
                 [("a", "A"), ("b", "B"), ("c", "C"), ("d", "D"), ("e", "E")], phone_columns={"b"})
    assert csv.split("\r\n")[1] == "73,5;+380 (67) 111-22-33;'-1+1;'=1+1;5"


def test_csv_phone_exemption_only_for_phone_column():
    """Phone-like values outside phone columns are still apostrophe-escaped."""
    row = {"phone": "+380 67 111", "name": "+380 67 111", "note": "-(1)-2"}
    csv = to_csv([row], [("phone", "Т"), ("name", "П"), ("note", "К")], phone_columns={"phone"})
    assert csv.split("\r\n")[1] == "+380 67 111;'+380 67 111;'-(1)-2"
    assert to_csv([{"x": "+=HYPERLINK(1)"}], [("x", "X")]).split("\r\n")[1] == "'+=HYPERLINK(1)"


def test_export_phone_not_prefixed(admin, lab):
    admin.patch(f"/api/students/{lab['border']}", json={"phone": "+380 67 111 22 33"})
    text = admin.get(f"/api/students/export?group_id={lab['group']}").content.decode("utf-8-sig")
    row = next(line for line in text.split("\r\n") if "MET-BORDER" in line)
    assert ";+380 67 111 22 33;" in row and ";73,5;" in row
