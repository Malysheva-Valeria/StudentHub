"""Data integrity: grading/attendance rules, one grade per lesson, student validation."""
from app.utils import local_today
from datetime import timedelta

import pytest

YESTERDAY = (local_today() - timedelta(days=1)).isoformat()


@pytest.fixture(scope="module")
def world(admin, db):
    """Dedicated group, subject and students with known state."""
    teacher_id = db.execute("SELECT id FROM users WHERE username = 'teacher'").fetchone()["id"]
    g = admin.post("/api/groups", json={"name": "INT-1", "course": 1, "specialty": "x"}).json()
    g2 = admin.post("/api/groups", json={"name": "INT-2", "course": 1, "specialty": "x"}).json()
    subj = admin.post("/api/subjects", json={"name": "Цілісність даних", "credits": 3, "hours": 90, "semester": 1,
                                             "control": "credit", "teacher_id": teacher_id, "group_ids": [g["id"]]}).json()

    def student(book, group, **kw):
        body = {"last_name": "Тест", "first_name": book, "gender": "M", "record_book": book, "group_id": group,
                "enrolled_at": "2024-09-01", **kw}
        r = admin.post("/api/students", json=body)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    return {
        "subject": subj["id"], "group": g["id"],
        "a": student("int-a", g["id"]), "b": student("int-b", g["id"]), "c": student("int-c", g["id"]),
        "expelled": student("int-exp", g["id"], status="expelled"),
        "foreign": student("int-f", g2["id"]),
        "fresh": student("int-new", g["id"], enrolled_at=local_today().isoformat()),
    }


def grade(world, **kw):
    return {"student_id": world["a"], "subject_id": world["subject"], "value": 80, "type": "current", "date": YESTERDAY, **kw}


@pytest.mark.parametrize("who,key,expected", [
    ("expelled", "student_id", "Студент Тест int-exp не навчається"),
    # out-of-scope student: name hidden (see test_enrolment_error_hides_out_of_scope_names)
    ("foreign", "student_id", "Студента не знайдено"),
    # enrolled after the lesson date: error on `date`, with the student's name
    ("fresh", "date", f"Студент Тест int-new зарахований {local_today():%d.%m.%Y} — пізніше дати заняття"),
])
def test_enrolment_rules_single_grade(teacher, world, who, key, expected):
    r = teacher.post("/api/grades", json=grade(world, student_id=world[who]))
    assert r.status_code == 400 and expected in r.json()["details"][key], r.text


def test_date_rules(teacher, world):
    r = teacher.post("/api/grades", json=grade(world, date="1999-12-31"))
    assert r.status_code == 400 and "date" in r.json()["details"]
    r = teacher.post("/api/grades", json=grade(world, date="2999-01-01"))
    assert r.status_code == 400 and "date" in r.json()["details"]


def test_final_type_must_match_control(teacher, world):
    r = teacher.post("/api/grades", json=grade(world, type="exam"))
    assert r.status_code == 400 and "залік" in r.json()["details"]["type"]
    assert teacher.post("/api/grades", json=grade(world, type="credit", value=70)).status_code == 201


def test_duplicate_grade_is_409_and_patch_into_taken_slot(teacher, world):
    r1 = teacher.post("/api/grades", json=grade(world, type="module", value=55))
    assert r1.status_code == 201
    r2 = teacher.post("/api/grades", json=grade(world, type="module", value=60))
    assert r2.status_code == 409 and r2.json()["error"] == "Оцінка за це заняття вже існує — відредагуйте її"
    other = teacher.post("/api/grades", json=grade(world, type="current", value=61)).json()
    r = teacher.patch(f"/api/grades/{other['id']}", json={"type": "module"})
    assert r.status_code == 409


def test_patch_grade_validates_new_date(teacher, world):
    g = teacher.post("/api/grades", json=grade(world, student_id=world["b"], value=75)).json()
    assert teacher.patch(f"/api/grades/{g['id']}", json={"date": "2999-01-01"}).status_code == 400
    r = teacher.patch(f"/api/grades/{g['id']}", json={"type": "exam"})
    assert r.status_code == 400 and "type" in r.json()["details"]
    r = teacher.patch(f"/api/grades/{g['id']}", json={"value": None})
    assert r.status_code == 400 and r.json()["details"] == {"value": "Обовʼязкове поле"}
    assert teacher.patch(f"/api/grades/{g['id']}", json={"value": 77}).json()["value"] == 77


def test_bulk_is_upsert(teacher, world, db):
    day = (local_today() - timedelta(days=2)).isoformat()
    body = {"subject_id": world["subject"], "type": "current", "date": day,
            "records": [{"student_id": world["a"], "value": 70}, {"student_id": world["b"], "value": 71}]}
    assert teacher.post("/api/grades/bulk", json=body).json() == {"saved": 2}
    body["records"][0]["value"] = 95
    assert teacher.post("/api/grades/bulk", json=body).json() == {"saved": 2}
    rows = db.execute("SELECT value FROM grades WHERE subject_id = ? AND date = ? AND student_id = ?",
                      (world["subject"], day, world["a"])).fetchall()
    assert [r["value"] for r in rows] == [95], "оцінку замінено, а не продубльовано"


def test_bulk_errors_point_to_record(teacher, world):
    base = {"subject_id": world["subject"], "type": "current", "date": YESTERDAY}
    r = teacher.post("/api/grades/bulk", json={**base, "records": [
        {"student_id": world["a"], "value": 1}, {"student_id": world["c"], "value": None}, {"student_id": world["expelled"], "value": 2}]})
    assert r.status_code == 400 and "records.2.student_id" in r.json()["details"]
    r = teacher.post("/api/grades/bulk", json={**base, "records": [
        {"student_id": world["a"], "value": 1}, {"student_id": world["a"], "value": 2}]})
    assert r.status_code == 400 and r.json()["details"] == {"records.1.student_id": "Студента вказано двічі"}
    r = teacher.post("/api/grades/bulk", json={**base, "type": "exam", "records": [{"student_id": world["a"], "value": 1}]})
    assert r.status_code == 400 and "type" in r.json()["details"]


def test_attendance_rules(teacher, world, db):
    base = {"subject_id": world["subject"], "date": YESTERDAY}
    for who, i in (("foreign", 1), ("expelled", 1), ("fresh", 1)):
        r = teacher.post("/api/attendance/bulk", json={**base, "records": [
            {"student_id": world["a"], "status": "present"}, {"student_id": world[who], "status": "absent"}]})
        assert r.status_code == 400 and f"records.{i}.student_id" in r.json()["details"], who
    r = teacher.post("/api/attendance/bulk", json={**base, "records": [
        {"student_id": world["a"], "status": "present"}, {"student_id": world["a"], "status": "absent"}]})
    assert r.status_code == 400
    r = teacher.post("/api/attendance/bulk", json={**base, "date": "1999-01-01", "records": [{"student_id": world["a"], "status": "present"}]})
    assert r.status_code == 400 and "date" in r.json()["details"]
    assert db.execute("SELECT COUNT(*) AS c FROM attendance WHERE subject_id = ?", (world["subject"],)).fetchone()["c"] == 0


def test_enrolment_check_is_one_query(db, world):
    from app.rules import Scope, check_enrolment
    statements: list[str] = []
    db.set_trace_callback(statements.append)
    try:
        check_enrolment(db, world["subject"], YESTERDAY, {f"records.{i}.student_id": s for i, s in enumerate((world["a"], world["b"], world["c"]))},
                        Scope())
    finally:
        db.set_trace_callback(None)
    assert len(statements) == 1


# ---------- Students ----------
@pytest.mark.parametrize("patch,field", [
    ({"birth_date": "1899-12-31"}, "birth_date"),
    ({"birth_date": "2999-01-01"}, "birth_date"),
    ({"birth_date": "2010-01-01", "enrolled_at": "2009-09-01"}, "birth_date"),
    ({"enrolled_at": "1999-09-01"}, "enrolled_at"),
    ({"enrolled_at": (local_today() + timedelta(days=400)).isoformat()}, "enrolled_at"),
    ({"phone": "12-34-5"}, "phone"),
])
def test_student_validation_rules(admin, patch, field):
    body = {"last_name": "В", "first_name": "В", "gender": "F", "record_book": "VAL-1", "birth_date": "2005-01-01", **patch}
    r = admin.post("/api/students", json=body)
    assert r.status_code == 400 and field in r.json()["details"], r.text


def test_record_book_case_insensitive_unique(admin):
    r = admin.post("/api/students", json={"last_name": "Р", "first_name": "К", "gender": "M", "record_book": "кн-77"})
    assert r.status_code == 201 and r.json()["record_book"] == "КН-77"
    assert admin.post("/api/students", json={"last_name": "Р", "first_name": "К", "gender": "M", "record_book": "Кн-77"}).status_code == 409


def test_student_patch_null_required_field(admin, world):
    r = admin.patch(f"/api/students/{world['c']}", json={"last_name": None, "status": None})
    assert r.status_code == 400 and r.json()["details"] == {"last_name": "Обовʼязкове поле", "status": "Обовʼязкове поле"}
    r = admin.patch(f"/api/students/{world['c']}", json={"middle_name": None, "phone": "+380 (67) 111-22-33"})
    assert r.status_code == 200 and r.json()["phone"] == "+380 (67) 111-22-33"


def test_enrolment_error_hides_out_of_scope_names(teacher, admin, world):
    """Error text does not leak an out-of-scope student's name or status to a teacher."""
    for r in (teacher.post("/api/grades", json=grade(world, student_id=world["foreign"])),
              teacher.post("/api/attendance/bulk", json={"subject_id": world["subject"], "date": YESTERDAY,
                                                         "records": [{"student_id": world["foreign"], "status": "present"}]})):
        assert r.status_code == 400 and "int-f" not in r.text and "Студента не знайдено" in r.text
    # admin sees everyone, so the message includes the name
    r = admin.post("/api/grades", json=grade(world, student_id=world["foreign"]))
    assert r.status_code == 400 and "Група студента Тест int-f не вивчає" in r.json()["details"]["student_id"]
