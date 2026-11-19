"""Sessions, login rate limits, production config, headers, request limits."""
import logging
import os
import stat
import threading

import pytest
from fastapi.testclient import TestClient

from app import config, security
from app.config import ConfigError, load_settings
from app.security import RateLimiter

from .conftest import login


# ---------- Server-side sessions ----------
def test_logout_revokes_replayed_cookie(fresh_app):
    app, _ = fresh_app()
    c = login(TestClient(app), "admin", "admin123")
    stolen = c.cookies.get("sh_session")
    assert c.post("/api/auth/logout").status_code == 200
    replay = TestClient(app, cookies={"sh_session": stolen})
    assert replay.get("/api/auth/me").status_code == 401, "скопійована cookie після виходу недійсна"


def test_cookie_holds_only_session_id(fresh_app):
    app, settings = fresh_app()
    c = login(TestClient(app), "admin", "admin123")
    from app.db import connect
    conn = connect(settings.db_path)
    rows = conn.execute("SELECT * FROM sessions").fetchall()
    conn.close()
    assert len(rows) == 1 and rows[0]["expires_at"] - rows[0]["created_at"] == 8 * 3600
    assert "admin" not in c.cookies.get("sh_session")


def test_idle_timeout(fresh_app, monkeypatch):
    app, _ = fresh_app()
    c = login(TestClient(app), "teacher", "teacher123")
    t0 = security.now()
    monkeypatch.setattr(security, "now", lambda: t0 + 3600)       # 1h idle: still valid
    assert c.get("/api/auth/me").status_code == 200
    monkeypatch.setattr(security, "now", lambda: t0 + 3600 + 2 * 3600 - 10)  # previous request refreshed last_seen
    assert c.get("/api/auth/me").status_code == 200
    monkeypatch.setattr(security, "now", lambda: t0 + 3600 + 4 * 3600 + 1)  # > 2h idle
    assert c.get("/api/auth/me").status_code == 401


def test_absolute_lifetime(fresh_app, monkeypatch):
    app, _ = fresh_app()
    c = login(TestClient(app), "teacher", "teacher123")
    t0 = security.now()
    for hours in range(1, 8):  # activity does not extend past the 8h lifetime
        monkeypatch.setattr(security, "now", lambda h=hours: t0 + h * 3600)
        assert c.get("/api/auth/me").status_code == 200
    monkeypatch.setattr(security, "now", lambda: t0 + 8 * 3600 + 1)
    assert c.get("/api/auth/me").status_code == 401


def test_password_change_kills_other_sessions_and_highlights_field(fresh_app):
    app, _ = fresh_app()
    a = login(TestClient(app), "moroz", "teacher123")
    b = login(TestClient(app), "moroz", "teacher123")
    r = a.post("/api/auth/change-password", json={"current_password": "wrong", "new_password": "newpass1"})
    assert r.status_code == 400 and "current_password" in r.json()["details"]
    assert a.post("/api/auth/change-password", json={"current_password": "teacher123", "new_password": "newpass1"}).status_code == 200
    assert a.get("/api/auth/me").status_code == 200
    assert b.get("/api/auth/me").status_code == 401


def test_change_password_rate_limit_kills_sessions(fresh_app):
    app, _ = fresh_app()
    a = login(TestClient(app), "kovalchuk", "teacher123")
    b = login(TestClient(app), "kovalchuk", "teacher123")
    codes = [a.post("/api/auth/change-password", json={"current_password": f"bad{i}", "new_password": "zzzzzz"}).status_code
             for i in range(6)]
    assert codes == [400] * 5 + [429]
    assert a.get("/api/auth/me").status_code == 401 and b.get("/api/auth/me").status_code == 401


def test_blocking_user_deletes_sessions(fresh_app):
    app, settings = fresh_app()
    admin = login(TestClient(app), "admin", "admin123")
    t = login(TestClient(app), "lytvyn", "teacher123")
    uid = next(u["id"] for u in admin.get("/api/users").json() if u["username"] == "lytvyn")
    assert admin.patch(f"/api/users/{uid}", json={"is_active": False}).status_code == 200
    assert t.get("/api/auth/me").status_code == 401
    from app.db import connect
    conn = connect(settings.db_path)
    assert conn.execute("SELECT COUNT(*) AS c FROM sessions WHERE user_id = ?", (uid,)).fetchone()["c"] == 0
    conn.close()


def test_auth_config_demo_flag(fresh_app, tmp_path):
    app, _ = fresh_app()
    assert TestClient(app).get("/api/auth/config").json() == {"demo": True}
    app2, _ = fresh_app(db_path=str(tmp_path / "nodemo.db"), seed_demo=False)
    assert TestClient(app2).get("/api/auth/config").json() == {"demo": False}


# ---------- Login rate limiting ----------
def _post_login(app, ip: str, username: str, password: str) -> int:
    return TestClient(app, client=(ip, 1)).post("/api/auth/login", json={"username": username, "password": password}).status_code


@pytest.fixture
def fast_bcrypt(monkeypatch):
    """Skip bcrypt for wrong passwords so 100+ attempt tests run fast."""
    from app.routers import auth
    monkeypatch.setattr(auth, "verify_password",
                        lambda pw, h: pw in security.DEMO_PASSWORDS and security.verify_password(pw, h))


def test_rate_limit_per_user_and_ip(fresh_app):
    """10 failures lock a username+IP pair; another IP with the right password still logs in."""
    app, _ = fresh_app()
    codes = [_post_login(app, "10.0.0.1", "admin", f"x{i}") for i in range(11)]
    assert codes == [401] * 10 + [429]
    assert _post_login(app, "10.0.0.1", "admin", "admin123") == 429, "з цієї адреси підбір заблоковано"
    assert _post_login(app, "10.0.0.2", "admin", "admin123") == 200, "власник акаунта з іншої адреси входить"
    assert _post_login(app, "10.0.0.1", "teacher", "teacher123") == 200, "інші логіни з цієї адреси працюють"


def test_rate_limit_per_username_across_ips(fresh_app, fast_bcrypt):
    """100 failures for one username across IPs lock that username from any IP."""
    app, _ = fresh_app()
    codes = [_post_login(app, f"10.1.{i // 200}.{i % 200}", "admin", f"x{i}") for i in range(100)]
    assert codes == [401] * 100
    assert _post_login(app, "10.9.9.9", "admin", "admin123") == 429
    assert _post_login(app, "10.9.9.9", "teacher", "teacher123") == 200


def test_rate_limit_per_ip_across_usernames(fresh_app, fast_bcrypt):
    """50 failures from one IP across usernames lock that IP for all usernames."""
    app, _ = fresh_app()
    codes = [_post_login(app, "10.2.0.1", f"user{i}", "x") for i in range(51)]
    assert codes == [401] * 50 + [429]
    assert _post_login(app, "10.2.0.1", "teacher", "teacher123") == 429
    assert _post_login(app, "10.2.0.2", "teacher", "teacher123") == 200


def test_known_device_bypasses_shared_lockout(fresh_app, fast_bcrypt):
    """A known-device cookie bypasses shared username/IP lockouts but not the username+IP limit."""
    app, _ = fresh_app()
    owner = TestClient(app, client=("10.7.0.1", 1))
    assert owner.post("/api/auth/login", json={"username": "admin", "password": "admin123"}).status_code == 200
    assert "sh_device" in owner.cookies
    owner.post("/api/auth/logout")

    for i in range(100):  # lock username "admin" for unknown devices
        _post_login(app, f"10.8.{i // 200}.{i % 200}", "admin", f"x{i}")
    for i in range(50):   # lock the owner's IP for unknown devices
        _post_login(app, "10.7.0.1", f"user{i}", "x")
    assert _post_login(app, "10.9.9.9", "admin", "admin123") == 429
    assert _post_login(app, "10.7.0.1", "teacher", "teacher123") == 429

    assert owner.post("/api/auth/login", json={"username": "admin", "password": "admin123"}).status_code == 200

    # forged device cookie is ignored
    fake = TestClient(app, client=("10.9.9.9", 1), cookies={"sh_device": "forged"})
    assert fake.post("/api/auth/login", json={"username": "admin", "password": "admin123"}).status_code == 429
    # username+IP limit still applies to a known device
    owner.post("/api/auth/logout")
    codes = [owner.post("/api/auth/login", json={"username": "admin", "password": f"bad{i}"}).status_code for i in range(11)]
    assert codes == [401] * 10 + [429]


def test_successful_own_login_does_not_reset_counter(fresh_app):
    """Interleaving successful logins into another account does not reset the failure counter."""
    app, _ = fresh_app()
    c = TestClient(app, client=("10.2.0.1", 1))
    statuses = []
    for i in range(30):
        if i % 5 == 4:
            c.post("/api/auth/login", json={"username": "teacher", "password": "teacher123"})
        else:
            statuses.append(c.post("/api/auth/login", json={"username": "admin", "password": f"guess{i}"}).status_code)
    assert statuses.count(401) == 10 and statuses[-1] == 429


def test_login_limiter_concurrency(fresh_app):
    app, _ = fresh_app()
    results: list[int] = []
    barrier = threading.Barrier(30)

    def attempt(i: int) -> None:
        client = TestClient(app, client=("10.3.0.1", 1))
        barrier.wait()
        results.append(client.post("/api/auth/login", json={"username": "sydorenko", "password": f"bad{i}"}).status_code)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(401) == 10 and results.count(429) == 20


def test_rate_limiter_unit_atomic():
    limiter = RateLimiter({"k": 10})
    allowed: list[bool] = []
    barrier = threading.Barrier(30)

    def go():
        barrier.wait()
        allowed.append(limiter.hit(k="x"))

    threads = [threading.Thread(target=go) for _ in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert allowed.count(True) == 10


def test_rate_limiter_checks_every_key():
    limiter = RateLimiter({"a": 1, "b": 3})
    assert limiter.hit(a="1", b="x") and not limiter.hit(a="1", b="x")
    assert limiter.hit(a="2", b="x") and limiter.hit(a="3", b="x")   # "b" is now exhausted (3 of 3)
    assert not limiter.hit(a="4", b="x")
    limiter.refund(b="x")
    assert limiter.hit(a="5", b="x")


# ---------- Production config ----------
def test_production_requires_secret(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    with pytest.raises(ConfigError):
        load_settings()


def test_production_defaults(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", "s" * 40)
    monkeypatch.delenv("SEED_DEMO", raising=False)
    s = load_settings()
    assert s.production and not s.seed_demo and not s.demo
    monkeypatch.setenv("APP_ENV", "development")
    assert load_settings().seed_demo


def test_production_app(fresh_app, caplog):
    fresh_app()  # seed demo data in dev mode, then start in production
    with caplog.at_level(logging.WARNING, logger="studenthub"):
        app, _ = fresh_app(production=True, seed_demo=False)
    assert "демо-паролями" in caplog.text
    c = TestClient(app, base_url="https://testserver")
    assert c.get("/api/docs").status_code == 404 and c.get("/api/openapi.json").status_code == 404
    assert c.get("/api/auth/config").json() == {"demo": False}
    r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert "secure" in r.headers["set-cookie"].lower()
    assert "max-age" in r.headers["strict-transport-security"]


@pytest.mark.parametrize("env,message", [
    ({"SESSION_SECRET": "short-secret"}, "щонайменше 32"),
    ({"SESSION_SECRET": "s" * 40, "SEED_DEMO": "1"}, "демо-дані"),
])
def test_production_config_errors(monkeypatch, env, message):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SEED_DEMO", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ConfigError, match=message):
        load_settings()


def test_unknown_timezone_is_config_error(monkeypatch):
    monkeypatch.setenv("APP_TIMEZONE", "Mars/Olympus")
    with pytest.raises(ConfigError, match="tzdata"):
        load_settings()
    monkeypatch.setenv("APP_TIMEZONE", "Europe/Kyiv")
    load_settings()


# ---------- python -m app.create_admin / python -m app.seed ----------
@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    """Separate dev-mode database without demo data for CLI commands."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "cli.db"))
    return str(tmp_path / "cli.db")


def test_create_admin_function(cli_env):
    from app.create_admin import AdminError, create_or_update_admin
    from app.db import connect, init_db
    init_db(cli_env)
    db = connect(cli_env)
    assert create_or_update_admin(db, " Boss ", "long-enough-1", "Головний") == "created"
    db.execute("INSERT INTO users (username, password_hash, full_name, role) VALUES ('t', 'x', 'T', 'teacher')")
    boss = db.execute("SELECT * FROM users WHERE username = 'boss'").fetchone()
    assert boss["role"] == "admin" and security.verify_password("long-enough-1", boss["password_hash"])
    security.create_session(db, boss["id"], 3600)
    db.execute("UPDATE users SET is_active = 0 WHERE id = ?", (boss["id"],))
    assert create_or_update_admin(db, "boss", "another-pass", "Головний") == "updated"
    boss = db.execute("SELECT * FROM users WHERE username = 'boss'").fetchone()
    assert boss["is_active"] == 1 and security.verify_password("another-pass", boss["password_hash"])
    assert db.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()["c"] == 0, "старі сесії завершено"
    with pytest.raises(AdminError, match="мінімум 8"):
        create_or_update_admin(db, "boss2", "short", "X")
    with pytest.raises(AdminError, match="не є адміністратором"):
        create_or_update_admin(db, "t", "long-enough-1", "X")
    db.close()


def test_create_admin_cli(cli_env, monkeypatch, capsys):
    from app import create_admin
    assert create_admin.main(["--username", "root", "--password", "1234567"]) == 1
    assert "мінімум 8" in capsys.readouterr().err
    assert create_admin.main(["--username", "root", "--password", "12345678"]) == 0
    answers = iter(["secret-pass", "secret-pass"])
    monkeypatch.setattr(create_admin.getpass, "getpass", lambda prompt="": next(answers))
    monkeypatch.setattr("builtins.input", lambda prompt="": "root")
    assert create_admin.main([]) == 0 and "Пароль адміністратора змінено" in capsys.readouterr().out


def test_seed_cli_guards(cli_env, monkeypatch, capsys):
    from app import seed
    from app.db import connect, init_db
    init_db(cli_env)
    db = connect(cli_env)
    db.execute("INSERT INTO users (username, password_hash, full_name, role) VALUES ('real', 'x', 'Реальний', 'admin')")
    db.close()
    monkeypatch.setattr("builtins.input", lambda prompt="": "no")
    assert seed.main([]) == 1, "без підтвердження «yes» дані не чіпаємо"
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", "s" * 40)
    assert seed.main(["--yes"]) == 1 and "--force" in capsys.readouterr().err
    db = connect(cli_env)
    assert [r["username"] for r in db.execute("SELECT username FROM users")] == ["real"]
    db.close()


def test_no_hsts_in_development(anon):
    assert "strict-transport-security" not in anon.get("/login").headers


def test_secret_file_created_private(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATABASE_DIR", tmp_path)
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    first = load_settings().session_secret
    assert load_settings().session_secret == first, "секрет стабільний між перезапусками"
    if os.name == "posix":
        assert stat.S_IMODE((tmp_path / ".session_secret").stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="права доступу POSIX")
def test_db_file_private(settings, app):
    assert stat.S_IMODE(os.stat(settings.db_path).st_mode) == 0o600


# ---------- Headers and request limits ----------
def test_security_headers_on_errors(fresh_app):
    app, _ = fresh_app()

    @app.get("/api/boom", include_in_schema=False)
    def boom():
        raise RuntimeError("test")

    app.router.routes.insert(0, app.router.routes.pop())  # register before the /api/{rest} catch-all
    c = TestClient(app, raise_server_exceptions=False)
    for r in (c.get("/api/boom"), c.get("/api/nope"), c.post("/api/auth/login", content="{bad",
                                                                headers={"Content-Type": "application/json"})):
        assert r.headers["x-frame-options"] == "DENY", r.status_code
        assert "camera=()" in r.headers["permissions-policy"]
        assert "content-security-policy" in r.headers
    r = c.get("/api/boom")
    assert r.status_code == 500 and r.json() == {"error": "Внутрішня помилка сервера"}


def test_body_limit(anon):
    big = '{"username":"a","password":"' + "A" * (1024 * 1024 + 10) + '"}'
    r = anon.post("/api/auth/login", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and "1 МБ" in r.json()["error"]
    assert r.headers["x-content-type-options"] == "nosniff"

    def chunks():  # chunked, no Content-Length: limit enforced while reading
        for _ in range(20):
            yield b"A" * 100_000

    r = anon.post("/api/auth/login", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


@pytest.mark.parametrize("url", [
    "/api/grades/9223372036854775808", "/api/students/0", "/api/students?limit=999999999999",
    "/api/students?group_id=9223372036854775808", "/api/grades?from=2026-02-31", "/api/grades?type=oral",
    "/api/students?status=sleeping", "/api/students?gender=X", "/api/reports/groups?format=xml",
    "/api/attendance/sheet?group_id=abc&subject_id=1&date=2026-01-01", "/api/grades?student_id=1.5",
])
def test_invalid_params_are_400(admin, url):
    r = admin.get(url)
    assert r.status_code == 400 and r.json()["details"], url


def test_huge_ids_in_body_are_400(admin, today):
    r = admin.post("/api/grades", json={"student_id": 2**63, "subject_id": 1, "value": 1, "type": "current", "date": today})
    assert r.status_code == 400 and "student_id" in r.json()["details"]
    r = admin.patch("/api/students/1", json={"group_id": 2**63})
    assert r.status_code == 400 and "group_id" in r.json()["details"]


def test_put_removed_for_partial_resources(admin):
    for url in ("/api/students/1", "/api/grades/1", "/api/users/1"):
        assert admin.put(url, json={}).status_code == 405, url


def test_create_app_refuses_demo_seed_in_production(tmp_path):
    """create_app() itself refuses demo seeding in production, not just load_settings()."""
    import pytest
    from app.config import ConfigError, Settings
    from app.main import create_app

    s = Settings(db_path=str(tmp_path / "p.db"), session_secret="x" * 40, production=True, host="", port=0, seed_demo=True)
    with pytest.raises(ConfigError):
        create_app(s)


def test_admin_password_rejects_whitespace_padding():
    """Admin passwords that are blank or whitespace-padded to length are rejected."""
    from app.create_admin import AdminError, check_admin_password
    for bad in (" " * 12, "abc" + " " * 10):
        with pytest.raises(AdminError):
            check_admin_password(bad)
    check_admin_password("Str0ng-pass")
