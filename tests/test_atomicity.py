"""Checks and writes run in one transaction; uniqueness/reference errors report the offending field."""
from datetime import timedelta

import pytest

from app.db import connect, transaction
from app.deps import get_db
from app.utils import local_today

YESTERDAY = (local_today() - timedelta(days=1)).isoformat()


@pytest.fixture
def traced(app, settings):
    """Override the DB dependency with a connection that records every executed SQL statement."""
    statements: list[str] = []

    def traced_db():
        conn = connect(settings.db_path)
        conn.set_trace_callback(statements.append)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = traced_db
    yield statements
    app.dependency_overrides.pop(get_db)


def assert_in_one_transaction(statements: list[str], *needles: str) -> None:
    """Assert each SQL fragment ran between BEGIN IMMEDIATE and the following COMMIT/ROLLBACK."""
    begin = statements.index("BEGIN IMMEDIATE")
    end = next(i for i, s in enumerate(statements) if i > begin and s in ("COMMIT", "ROLLBACK"))
    for needle in needles:
        idx = next((i for i, s in enumerate(statements) if needle in s), None)
        assert idx is not None, f"не виконано: {needle}"
        assert begin < idx < end, f"поза транзакцією: {needle}"


@pytest.fixture(scope="module")
def ids(admin, db):
    teacher_id = db.execute("SELECT id FROM users WHERE username = 'teacher'").fetchone()["id"]
    g = admin.post("/api/groups", json={"name": "ATM-1", "course": 1, "specialty": "x"}).json()["id"]
    s = admin.post("/api/subjects", json={"name": "Атомарність", "credits": 1, "hours": 10, "semester": 1, "control": "exam",
                                          "teacher_id": teacher_id, "group_ids": [g]}).json()["id"]
    st = admin.post("/api/students", json={"last_name": "Ат", "first_name": "Ом", "gender": "M", "record_book": "ATM-S",
                                           "group_id": g, "enrolled_at": "2024-09-01"}).json()["id"]
    return {"group": g, "subject": s, "student": st}


def test_grade_writes_are_atomic(teacher, ids, traced):
    traced.clear()
    r = teacher.post("/api/grades", json={"student_id": ids["student"], "subject_id": ids["subject"], "value": 60,
                                          "type": "current", "date": YESTERDAY})
    assert r.status_code == 201
    assert_in_one_transaction(traced, "FROM students s", "INSERT INTO grades")
    gid = r.json()["id"]
    traced.clear()
    assert teacher.patch(f"/api/grades/{gid}", json={"value": 61}).status_code == 200
    assert_in_one_transaction(traced, "WHERE gr.id = ", "UPDATE grades")
    traced.clear()
    assert teacher.delete(f"/api/grades/{gid}").status_code == 204
    assert_in_one_transaction(traced, "WHERE gr.id = ", "DELETE FROM grades")
    traced.clear()
    bulk = {"subject_id": ids["subject"], "type": "current", "date": YESTERDAY, "records": [{"student_id": ids["student"], "value": 70}]}
    assert teacher.post("/api/grades/bulk", json=bulk).status_code == 201
    assert_in_one_transaction(traced, "FROM students s", "INSERT INTO grades")
    traced.clear()
    att = {"subject_id": ids["subject"], "date": YESTERDAY, "records": [{"student_id": ids["student"], "status": "late"}]}
    assert teacher.post("/api/attendance/bulk", json=att).status_code == 200
    assert_in_one_transaction(traced, "FROM students s", "INSERT INTO attendance")


@pytest.mark.parametrize("kind,check", [
    ("students", "FROM grades WHERE student_id"),
    ("subjects", "FROM grades WHERE subject_id"),
    ("groups", "FROM students WHERE group_id"),
])
def test_delete_check_and_delete_in_one_transaction(admin, ids, traced, kind, check):
    key = {"students": "student", "subjects": "subject", "groups": "group"}[kind]
    traced.clear()
    assert admin.delete(f"/api/{kind}/{ids[key]}").status_code == 409
    assert_in_one_transaction(traced, check)
    assert "ROLLBACK" in traced


def test_user_delete_in_one_transaction(admin, traced):
    u = admin.post("/api/users", json={"username": "atomic", "password": "secret1", "full_name": "А", "role": "teacher"}).json()
    traced.clear()
    assert admin.delete(f"/api/users/{u['id']}").status_code == 204
    assert_in_one_transaction(traced, "FROM grades WHERE teacher_id", "DELETE FROM users")
    assert "COMMIT" in traced


def test_transaction_survives_rollback_by_sqlite(tmp_path):
    """transaction() re-raises the original error when SQLite has already rolled back."""
    conn = connect(str(tmp_path / "t.db"))
    with pytest.raises(ValueError, match="справжня причина"):
        with transaction(conn):
            conn.execute("ROLLBACK")  # simulate SQLite's automatic rollback
            raise ValueError("справжня причина")
    assert not conn.in_transaction
    conn.close()


# ---------- Uniqueness (409) and missing references (400) ----------
def test_unique_conflicts_have_field_details(admin, ids):
    r = admin.post("/api/students", json={"last_name": "Д", "first_name": "Д", "gender": "M", "record_book": "atm-s"})
    assert r.status_code == 409 and "record_book" in r.json()["details"]
    other = admin.post("/api/students", json={"last_name": "Д", "first_name": "Д", "gender": "M", "record_book": "ATM-S2"}).json()
    r = admin.patch(f"/api/students/{other['id']}", json={"record_book": "ATM-S"})
    assert r.status_code == 409 and "record_book" in r.json()["details"]
    r = admin.post("/api/groups", json={"name": "atm-1", "course": 1, "specialty": "x"})
    assert r.status_code == 409 and "name" in r.json()["details"]
    r = admin.post("/api/subjects", json={"name": "АТОМАРНІСТЬ", "credits": 1, "hours": 10, "semester": 1, "control": "exam"})
    assert r.status_code == 409 and "name" in r.json()["details"]
    r = admin.post("/api/users", json={"username": "Teacher", "password": "secret1", "full_name": "Х", "role": "teacher"})
    assert r.status_code == 409 and "username" in r.json()["details"]


@pytest.mark.parametrize("url,method,body,field", [
    ("/api/students", "post", {"last_name": "Н", "first_name": "Н", "gender": "M", "record_book": "REF-1", "group_id": 999999}, "group_id"),
    ("/api/groups", "post", {"name": "REF-G", "course": 1, "specialty": "x", "curator_id": 999999}, "curator_id"),
    ("/api/groups", "post", {"name": "REF-G", "course": 1, "specialty": "x", "subject_ids": [1, 999999]}, "subject_ids"),
    ("/api/subjects", "post", {"name": "REF-S", "credits": 1, "hours": 1, "semester": 1, "control": "exam", "teacher_id": 999999}, "teacher_id"),
    ("/api/subjects", "post", {"name": "REF-S", "credits": 1, "hours": 1, "semester": 1, "control": "exam", "group_ids": [999999]}, "group_ids"),
])
def test_missing_references_are_400_with_field(admin, url, method, body, field):
    r = getattr(admin, method)(url, json=body)
    assert r.status_code == 400 and field in r.json()["details"], r.text

