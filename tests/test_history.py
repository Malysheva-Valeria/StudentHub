"""Grade/attendance history: group snapshots, student transfers, group-subject links, control type, sheets, edit scope."""
from datetime import timedelta

import pytest

from app.utils import local_today

TODAY = local_today()
D1 = (TODAY - timedelta(days=10)).isoformat()
D2 = (TODAY - timedelta(days=3)).isoformat()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()


@pytest.fixture(scope="module")
def w(admin, db):
    """Groups A and B share one credit subject taught by `teacher`; students X and Y start in A."""
    teacher_id = db.execute("SELECT id FROM users WHERE username = 'teacher'").fetchone()["id"]
    a = admin.post("/api/groups", json={"name": "HIS-A", "course": 1, "specialty": "x"}).json()["id"]
    b = admin.post("/api/groups", json={"name": "HIS-B", "course": 1, "specialty": "x"}).json()["id"]
    subj = admin.post("/api/subjects", json={"name": "Історія оцінок", "credits": 3, "hours": 90, "semester": 1,
                                             "control": "credit", "teacher_id": teacher_id, "group_ids": [a, b]}).json()["id"]

    def student(book, group, **kw):
        r = admin.post("/api/students", json={"last_name": "Іст", "first_name": book, "gender": "M", "record_book": book,
                                              "group_id": group, "enrolled_at": "2024-09-01", **kw})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    return {"a": a, "b": b, "subject": subj, "x": student("HIS-X", a), "y": student("HIS-Y", a)}


def journal(client, w, group):
    r = client.get(f"/api/grades/journal?group_id={group}&subject_id={w['subject']}")
    assert r.status_code == 200, r.text
    return r.json()


def sheet(client, w, group, day):
    return client.get(f"/api/attendance/sheet?group_id={group}&subject_id={w['subject']}&date={day}")


# ---------- Group snapshot ----------
def test_moved_student_grades_stay_in_old_group(admin, teacher, w, db):
    g = teacher.post("/api/grades", json={"student_id": w["x"], "subject_id": w["subject"], "value": 77,
                                          "type": "current", "date": D1}).json()
    assert g["group_id"] == w["a"] and g["group_name"] == "HIS-A"
    att = {"subject_id": w["subject"], "date": D1, "records": [{"student_id": w["x"], "status": "present"},
                                                               {"student_id": w["y"], "status": "absent"}]}
    assert teacher.post("/api/attendance/bulk", json=att).status_code == 200

    assert admin.patch(f"/api/students/{w['x']}", json={"group_id": w["b"]}).status_code == 200  # move X to B

    old = journal(teacher, w, w["a"])
    row = next(r for r in old["rows"] if r["id"] == w["x"])
    assert row["former"] is True and row["cells"][f"{D1}|current"]["value"] == 77
    assert [c["date"] for c in old["columns"]] == [D1]
    new = journal(teacher, w, w["b"])
    row = next(r for r in new["rows"] if r["id"] == w["x"])
    assert row["former"] is False and row["cells"] == {} and new["columns"] == [], "старі оцінки не переходять у нову групу"

    # grade list and group filter use the snapshot group
    assert [i["id"] for i in teacher.get(f"/api/grades?group_id={w['a']}").json()["items"]] == [g["id"]]
    assert teacher.get(f"/api/grades?group_id={w['b']}").json()["total"] == 0
    assert teacher.get(f"/api/grades/{g['id']}").json()["group_name"] == "HIS-A"

    # new grades land in the new group
    g2 = teacher.post("/api/grades", json={"student_id": w["x"], "subject_id": w["subject"], "value": 90,
                                           "type": "current", "date": D2}).json()
    assert g2["group_id"] == w["b"]
    assert [c["date"] for c in journal(teacher, w, w["b"])["columns"]] == [D2]

    # sheet is "marked" only for the group where attendance was taken
    assert sheet(teacher, w, w["a"], D1).json()["marked"] is True
    assert {r["student_id"] for r in sheet(teacher, w, w["a"], D1).json()["rows"]} == {w["y"]}
    assert sheet(teacher, w, w["b"], D1).json()["marked"] is False
    snap = db.execute("SELECT group_id FROM attendance WHERE student_id = ? AND date = ?", (w["x"], D1)).fetchone()
    assert snap["group_id"] == w["a"]


def test_student_metrics_stay_per_student(admin, w):
    card = admin.get(f"/api/students/{w['x']}").json()
    assert card["avg_grade"] == 83.5, "середній бал студента — з усіх його оцінок, незалежно від групи"


# ---------- Grade editing and scope ----------
def test_historical_grade_value_edit_and_scope_404(admin, teacher, make_client, w, db):
    old = db.execute("SELECT id FROM grades WHERE student_id = ? AND date = ?", (w["x"], D1)).fetchone()["id"]
    assert teacher.patch(f"/api/grades/{old}", json={"value": 80}).json()["value"] == 80, "переведеного — можна"
    gy = teacher.post("/api/grades", json={"student_id": w["y"], "subject_id": w["subject"], "value": 50,
                                           "type": "current", "date": D1}).json()["id"]
    admin.patch(f"/api/students/{w['y']}", json={"status": "expelled"})
    assert teacher.patch(f"/api/grades/{gy}", json={"comment": "перескладання"}).status_code == 200, "відрахованого — можна"
    assert teacher.patch(f"/api/grades/{gy}", json={"date": D2}).status_code == 400, "дату — за правилами нової оцінки"

    admin.post("/api/users", json={"username": "outsider", "password": "secret1", "full_name": "Сторонній", "role": "teacher"})
    outsider = make_client("outsider", "secret1")
    for call in (outsider.get, outsider.delete):
        assert call(f"/api/grades/{old}").status_code == 404
    assert outsider.patch(f"/api/grades/{old}", json={"value": 1}).status_code == 404, "поза областю — 404, а не 403"


# ---------- Unlinking a group from a subject ----------
def test_unlink_with_history_is_409(admin, w):
    r = admin.put(f"/api/groups/{w['a']}", json={"name": "HIS-A", "course": 1, "specialty": "x", "subject_ids": []})
    assert r.status_code == 409 and "Неможливо відвʼязати" in r.json()["error"] and "Історія оцінок" in r.json()["error"]
    assert "subject_ids" in r.json()["details"], "помилка показується біля списку дисциплін у формі групи"
    r = admin.put(f"/api/subjects/{w['subject']}", json={"name": "Історія оцінок", "credits": 3, "hours": 90, "semester": 1,
                                                         "control": "credit", "group_ids": [w["b"]]})
    assert r.status_code == 409 and "HIS-A" in r.json()["error"] and "group_ids" in r.json()["details"]
    assert admin.get(f"/api/groups/{w['a']}").json()["subject_ids"] == [w["subject"]], "нічого не змінено"
    # adding a link is always allowed
    extra = admin.post("/api/subjects", json={"name": "Додаткова", "credits": 1, "hours": 10, "semester": 1, "control": "exam"}).json()
    r = admin.put(f"/api/groups/{w['a']}", json={"name": "HIS-A", "course": 1, "specialty": "x",
                                                 "subject_ids": [w["subject"], extra["id"]]})
    assert r.status_code == 200 and sorted(r.json()["subject_ids"]) == sorted([w["subject"], extra["id"]])
    # a link without history can be removed
    r = admin.put(f"/api/groups/{w['a']}", json={"name": "HIS-A", "course": 1, "specialty": "x", "subject_ids": [w["subject"]]})
    assert r.status_code == 200


def test_group_with_history_cannot_be_deleted(admin, w):
    admin.patch(f"/api/students/{w['y']}", json={"group_id": w["b"]})
    assert admin.delete(f"/api/groups/{w['a']}").status_code == 409


# ---------- Changing control type ----------
def test_control_change_with_final_grades_is_409(admin, teacher, w):
    assert teacher.post("/api/grades", json={"student_id": w["x"], "subject_id": w["subject"], "value": 70,
                                             "type": "credit", "date": D2}).status_code == 201
    body = {"name": "Історія оцінок", "credits": 3, "hours": 90, "semester": 1, "control": "exam",
            "group_ids": [w["a"], w["b"]]}
    r = admin.put(f"/api/subjects/{w['subject']}", json=body)
    assert r.status_code == 409 and "control" in r.json()["details"]
    plain = admin.post("/api/subjects", json={"name": "Без підсумкових", "credits": 1, "hours": 10, "semester": 1, "control": "exam"}).json()
    r = admin.put(f"/api/subjects/{plain['id']}", json={"name": "Без підсумкових", "credits": 1, "hours": 10, "semester": 1,
                                                        "control": "credit"})
    assert r.status_code == 200 and r.json()["control"] == "credit"


# ---------- Mid-year enrolment ----------
def test_sheet_lists_only_students_enrolled_by_date(admin, teacher, w):
    newbie = admin.post("/api/students", json={"last_name": "Новенький", "first_name": "Н", "gender": "M",
                                               "record_book": "HIS-NEW", "group_id": w["b"]}).json()["id"]  # enrolled today
    past = sheet(teacher, w, w["b"], YESTERDAY).json()
    assert newbie not in {r["student_id"] for r in past["rows"]}
    assert newbie in {r["student_id"] for r in sheet(teacher, w, w["b"], TODAY.isoformat()).json()["rows"]}
    records = [{"student_id": r["student_id"], "status": "present"} for r in past["rows"]]
    assert teacher.post("/api/attendance/bulk", json={"subject_id": w["subject"], "date": YESTERDAY,
                                                      "records": records}).status_code == 200
    j = journal(teacher, w, w["b"])
    assert next(r for r in j["rows"] if r["id"] == newbie)["enrolled_at"] == TODAY.isoformat(), \
        "журнал повертає дату зарахування — фронтенд фільтрує список «Нове заняття»"
    r = teacher.post("/api/attendance/bulk", json={"subject_id": w["subject"], "date": YESTERDAY,
                                                   "records": [{"student_id": newbie, "status": "present"}]})
    assert r.status_code == 400 and "Новенький Н зарахований" in r.json()["details"]["records.0.student_id"]


# ---------- Sheet parameter validation ----------
def test_sheet_validation(teacher, admin, w):
    future = (TODAY + timedelta(days=1)).isoformat()
    for day in (future, "1999-12-31"):
        r = sheet(teacher, w, w["b"], day)
        assert r.status_code == 400 and "date" in r.json()["details"], day
    other = admin.post("/api/groups", json={"name": "HIS-C", "course": 1, "specialty": "x"}).json()["id"]
    r = admin.get(f"/api/attendance/sheet?group_id={other}&subject_id={w['subject']}&date={YESTERDAY}")
    assert r.status_code == 400 and r.json()["error"] == "Група не вивчає цю дисципліну"
    assert admin.get(f"/api/grades/journal?group_id={other}&subject_id={w['subject']}").status_code == 400
    assert admin.get("/api/groups/999999/subjects").status_code == 404


# ---------- Subject average ----------
def test_subject_avg_is_mean_of_student_averages(admin, w):
    admin.patch(f"/api/students/{w['y']}", json={"status": "active"})
    s = admin.post("/api/subjects", json={"name": "Середні бали", "credits": 1, "hours": 10, "semester": 1, "control": "exam",
                                          "teacher_id": None, "group_ids": [w["b"]]}).json()
    for day, value in ((D1, 100), (D2, 100), (YESTERDAY, 100)):
        admin.post("/api/grades", json={"student_id": w["x"], "subject_id": s["id"], "value": value, "type": "current", "date": day})
    admin.post("/api/grades", json={"student_id": w["y"], "subject_id": s["id"], "value": 50, "type": "current", "date": D1})
    # (100 + 50) / 2 = 75, not the mean of all 4 grades (87.5)
    assert admin.get(f"/api/subjects/{s['id']}").json()["avg_grade"] == 75
    assert next(x for x in admin.get("/api/subjects").json() if x["id"] == s["id"])["avg_grade"] == 75
    admin.patch(f"/api/students/{w['y']}", json={"status": "expelled"})
    assert admin.get(f"/api/subjects/{s['id']}").json()["avg_grade"] == 100, "лише активні студенти"


def test_moved_student_old_records_cannot_be_overwritten_from_new_group(teacher, w, db):
    """Bulk saves from the new group cannot overwrite a moved student's records in the old group."""
    rows = sheet(teacher, w, w["b"], D1).json()["rows"]
    assert w["x"] not in {r["student_id"] for r in rows}

    before = db.execute("SELECT status, group_id FROM attendance WHERE student_id = ? AND subject_id = ? AND date = ?",
                        (w["x"], w["subject"], D1)).fetchone()
    r = teacher.post("/api/attendance/bulk", json={"subject_id": w["subject"], "date": D1,
                                                   "records": [{"student_id": w["x"], "status": "absent"}]})
    assert r.status_code == 409 and "HIS-A" in r.json()["details"]["records.0.student_id"]
    after = db.execute("SELECT status, group_id FROM attendance WHERE student_id = ? AND subject_id = ? AND date = ?",
                       (w["x"], w["subject"], D1)).fetchone()
    assert after == before

    grade_sql = "SELECT value, group_id FROM grades WHERE student_id = ? AND subject_id = ? AND date = ? AND type = 'current'"
    g_before = db.execute(grade_sql, (w["x"], w["subject"], D1)).fetchone()
    assert g_before["group_id"] == w["a"]
    r = teacher.post("/api/grades/bulk", json={"subject_id": w["subject"], "type": "current", "date": D1,
                                               "records": [{"student_id": w["x"], "value": 10}]})
    assert r.status_code == 409 and "records.0.student_id" in r.json()["details"]
    assert db.execute(grade_sql, (w["x"], w["subject"], D1)).fetchone() == g_before
