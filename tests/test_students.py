NEW = {
    "last_name": "Тестенко", "first_name": "Іван", "middle_name": "Петрович", "gender": "M",
    "record_book": "T-0001", "group_id": 1, "email": "ivan@test.ua", "birth_date": "2005-05-05",
}


def count(db, sql, *p):
    return next(iter(db.execute(sql, p).fetchone().values()))


def test_list_pagination(admin, db):
    r = admin.get("/api/students?limit=10&page=2").json()
    assert len(r["items"]) == 10 and r["page"] == 2
    assert r["total"] == count(db, "SELECT COUNT(*) FROM students")
    assert {"avg_grade", "attendance_rate", "group_name"} <= r["items"][0].keys()


def test_search_cyrillic_case_insensitive(admin, db):
    one = db.execute("SELECT * FROM students WHERE last_name = 'Бойко' LIMIT 1").fetchone()
    found = admin.get("/api/students", params={"search": "бойко", "limit": 500}).json()["items"]
    assert any(s["id"] == one["id"] for s in found)
    assert all("бойко" in s["last_name"].lower() for s in found)
    assert admin.get("/api/students", params={"search": one["record_book"]}).json()["items"][0]["id"] == one["id"]


def test_search_like_wildcards_are_escaped(admin):
    assert admin.get("/api/students", params={"search": "%"}).json()["total"] == 0
    assert admin.get("/api/students", params={"search": "_"}).json()["total"] == 0


def test_filters_and_sort(admin):
    items = admin.get("/api/students?group_id=2&limit=500").json()["items"]
    assert items and all(s["group_id"] == 2 for s in items)
    items = admin.get("/api/students?gender=F&status=active&limit=500").json()["items"]
    assert all(s["gender"] == "F" and s["status"] == "active" for s in items)
    avgs = [s["avg_grade"] for s in admin.get("/api/students?sort=avg&limit=50").json()["items"] if s["avg_grade"] is not None]
    assert avgs == sorted(avgs, reverse=True)
    r = admin.get("/api/students?sort=;DROP TABLE students&page=abc&limit=-5")
    assert r.status_code == 400 and {"sort", "page", "limit"} <= r.json()["details"].keys()


def test_ukrainian_alphabetical_order(admin):
    names = [s["last_name"] for s in admin.get("/api/students?sort=name&limit=500").json()["items"]]
    alphabet = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя"
    firsts = [alphabet.index(n[0].lower()) for n in names]
    assert firsts == sorted(firsts), "І/Є йдуть за українським алфавітом, а не за кодами Unicode"


def test_crud(admin):
    r = admin.post("/api/students", json=NEW)
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["status"] == "active" and s["group_name"] == "КН-11" and s["enrolled_at"]
    card = admin.get(f"/api/students/{s['id']}").json()
    assert card["subjects"] == [] and card["attendance"]["total"] == 0
    upd = admin.patch(f"/api/students/{s['id']}", json={"status": "academic_leave", "phone": "+380501112233"}).json()
    assert upd["status"] == "academic_leave" and upd["last_name"] == "Тестенко"
    assert admin.patch(f"/api/students/{s['id']}", json={"last_name": ""}).status_code == 400
    assert admin.delete(f"/api/students/{s['id']}").status_code == 204
    assert admin.get(f"/api/students/{s['id']}").status_code == 404
    assert admin.delete(f"/api/students/{s['id']}").status_code == 404


def test_validation(admin):
    r = admin.post("/api/students", json={"last_name": "  ", "gender": "X", "email": "bad", "birth_date": "2020-02-31", "phone": "abc"})
    assert r.status_code == 400
    d = r.json()["details"]
    for f in ("last_name", "first_name", "gender", "record_book", "email", "birth_date", "phone"):
        assert f in d, f
    assert d["email"] == "Некоректний email"
    assert admin.get("/api/students/abc").status_code == 400


def test_unique_and_fk(admin):
    assert admin.post("/api/students", json={**NEW, "record_book": "DUP-1"}).status_code == 201
    assert admin.post("/api/students", json={**NEW, "record_book": "DUP-1"}).status_code == 409
    assert admin.post("/api/students", json={**NEW, "record_book": "FK-1", "group_id": 9999}).status_code == 400


def test_delete_student_with_history_is_409(admin, db):
    sid = db.execute("SELECT student_id FROM grades LIMIT 1").fetchone()["student_id"]
    before = count(db, "SELECT COUNT(*) FROM grades WHERE student_id = ?", sid)
    r = admin.delete(f"/api/students/{sid}")
    assert r.status_code == 409 and "статус" in r.json()["error"]
    assert count(db, "SELECT COUNT(*) FROM grades WHERE student_id = ?", sid) == before, "історія не втрачена"
    assert admin.get(f"/api/students/{sid}").status_code == 200


def test_teacher_read_only(teacher):
    assert teacher.get("/api/students").status_code == 200
    assert teacher.post("/api/students", json=NEW).status_code == 403
    assert teacher.patch("/api/students/2", json={"status": "expelled"}).status_code == 403
    assert teacher.delete("/api/students/2").status_code == 403


def test_export_csv(admin, db):
    r = admin.get("/api/students/export?group_id=1")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.content.decode("utf-8-sig").split("\r\n")
    assert lines[0].startswith("Залікова книжка;ПІБ;Група")
    assert len(lines) - 1 == count(db, "SELECT COUNT(*) FROM students WHERE group_id = 1")
