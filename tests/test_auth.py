from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def test_api_requires_auth(anon):
    for url in ("/api/students", "/api/dashboard", "/api/grades", "/api/auth/me", "/api/reports/groups"):
        assert anon.get(url).status_code == 401, url


def test_login_session_logout(make_client):
    c = make_client()
    r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "admin"
    assert "password_hash" not in r.json()["user"]
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert c.get("/api/auth/me").json()["user"]["username"] == "admin"
    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/api/auth/me").status_code == 401


def test_username_case_insensitive(make_client):
    make_client("ADMIN", "admin123")


def test_wrong_password_and_validation(anon):
    r = anon.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401
    assert r.json()["error"] == "Невірний логін або пароль"
    r = anon.post("/api/auth/login", json={})
    assert r.status_code == 400
    assert r.json()["details"]["username"] == "Обовʼязкове поле"


def test_invalid_json(anon):
    r = anon.post("/api/auth/login", content="{oops", headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    assert r.json()["error"] == "Некоректний JSON"


def test_change_password_invalidates_other_sessions(make_client):
    a = make_client("moroz", "teacher123")
    b = make_client("moroz", "teacher123")
    assert a.post("/api/auth/change-password", json={"current_password": "nope", "new_password": "newpass1"}).status_code == 400
    assert a.post("/api/auth/change-password", json={"current_password": "teacher123", "new_password": "123"}).status_code == 400
    assert a.post("/api/auth/change-password", json={"current_password": "teacher123", "new_password": "newpass1"}).status_code == 200
    assert a.get("/api/auth/me").status_code == 200, "поточна сесія лишається"
    assert b.get("/api/auth/me").status_code == 401, "інші сесії завершено"
    make_client("moroz", "newpass1")


def test_blocked_user_loses_session(admin, make_client, anon):
    t = make_client("lytvyn", "teacher123")
    uid = next(u["id"] for u in admin.get("/api/users").json() if u["username"] == "lytvyn")
    assert admin.patch(f"/api/users/{uid}", json={"is_active": 0}).status_code == 200
    assert t.get("/api/auth/me").status_code == 401
    assert anon.post("/api/auth/login", json={"username": "lytvyn", "password": "teacher123"}).status_code == 401


def test_too_long_password_does_not_crash(anon):
    r = anon.post("/api/auth/login", json={"username": "admin", "password": "я" * 100})
    assert r.status_code == 401


def test_rate_limit(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "rl.db"), session_secret="x", production=False, host="", port=0))
    c = TestClient(app)
    codes = [c.post("/api/auth/login", json={"username": "admin", "password": "x"}).status_code for _ in range(11)]
    assert codes[-1] == 429
    assert c.post("/api/auth/login", json={"username": "admin", "password": "admin123"}).status_code == 429


def test_pages_static_and_headers(anon, admin):
    for url in ("/", "/login", "/students", "/css/style.css", "/vendor/chart.umd.min.js", "/js/login.js"):
        assert anon.get(url).status_code == 200, url
    r = anon.get("/login")
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert anon.get("/no-such-page").status_code == 404
    assert admin.get("/api/nope").status_code == 404
    assert admin.get("/api/students").headers["cache-control"] == "no-store"


def test_me_returns_server_today_and_ects_scale(admin, today):
    from app.grading import ECTS
    body = admin.get("/api/auth/me").json()
    assert body["today"] == today
    assert body["ects"] == ECTS
