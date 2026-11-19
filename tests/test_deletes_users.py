"""Deleting records with history (409) and last-admin protection."""
from fastapi.testclient import TestClient

from .conftest import login


def test_admins_can_manage_each_other_but_not_themselves(fresh_app):
    app, _ = fresh_app()
    admin = login(TestClient(app), "admin", "admin123")
    me = admin.get("/api/auth/me").json()["user"]
    second = admin.post("/api/users", json={"username": "admin2", "password": "secret1", "full_name": "Другий", "role": "admin"}).json()
    other = login(TestClient(app), "admin2", "secret1")
    assert other.patch(f"/api/users/{second['id']}", json={"is_active": False}).status_code == 400
    assert other.patch(f"/api/users/{me['id']}", json={"role": "teacher"}).status_code == 200
    assert admin.get("/api/users").status_code == 403, "права змінюються одразу"


def test_last_active_admin_protected_against_race(fresh_app):
    """Two admins demoting each other concurrently: the second request gets 409."""
    from app.db import connect
    from app.errors import ApiError
    from app.routers.users import update_user
    from app.schemas import UserUpdate

    app, settings = fresh_app()
    admin = login(TestClient(app), "admin", "admin123")
    a_id = admin.get("/api/auth/me").json()["user"]["id"]
    b = admin.post("/api/users", json={"username": "admin2", "password": "secret1", "full_name": "Другий", "role": "admin"}).json()
    conn = connect(settings.db_path)
    stale_b = dict(conn.execute("SELECT * FROM users WHERE id = ?", (b["id"],)).fetchone())  # B's permissions checked before demotion
    update_user(b["id"], UserUpdate(role="teacher"), admin={"id": a_id}, db=conn)          # A demotes B
    try:
        update_user(a_id, UserUpdate(role="teacher"), admin=stale_b, db=conn)              # stale B demotes A
    except ApiError as e:
        assert e.status == 409 and "останній активний адміністратор" in e.message
    else:
        raise AssertionError("очікувався 409")
    assert conn.execute("SELECT role FROM users WHERE id = ?", (a_id,)).fetchone()["role"] == "admin"
    conn.close()


def test_teachers_endpoint_includes_blocked(admin):
    u = admin.post("/api/users", json={"username": "blk", "password": "secret1", "full_name": "Блокований Б", "role": "teacher"}).json()
    admin.patch(f"/api/users/{u['id']}", json={"is_active": False})
    items = admin.get("/api/users/teachers").json()
    row = next(i for i in items if i["id"] == u["id"])
    assert row == {"id": u["id"], "full_name": "Блокований Б", "is_active": 0}
    assert any(i["full_name"] == "Адміністратор системи" for i in items), "адміністратори теж у списку"


def test_user_delete_rules(admin, db):
    fresh = admin.post("/api/users", json={"username": "tmpdel", "password": "secret1", "full_name": "Тимчасовий", "role": "teacher"}).json()
    assert admin.delete(f"/api/users/{fresh['id']}").status_code == 204
    curator = admin.post("/api/users", json={"username": "cur9", "password": "secret1", "full_name": "Куратор", "role": "teacher"}).json()
    admin.post("/api/groups", json={"name": "CUR-9", "course": 1, "specialty": "x", "curator_id": curator["id"]})
    r = admin.delete(f"/api/users/{curator['id']}")
    assert r.status_code == 409 and "заблокуйте" in r.json()["error"]
    graded = db.execute("SELECT teacher_id FROM grades WHERE teacher_id IS NOT NULL LIMIT 1").fetchone()["teacher_id"]
    assert admin.delete(f"/api/users/{graded}").status_code == 409


def test_subject_delete_rules(admin):
    s = admin.post("/api/subjects", json={"name": "Порожня", "credits": 1, "hours": 10, "semester": 1, "control": "exam"}).json()
    assert admin.delete(f"/api/subjects/{s['id']}").status_code == 204
    r = admin.delete("/api/subjects/1")
    assert r.status_code == 409 and "оцінки" in r.json()["error"]
    assert admin.get("/api/subjects/1").status_code == 200
