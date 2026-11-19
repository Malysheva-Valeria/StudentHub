def test_group_crud_with_subjects(admin):
    r = admin.post("/api/groups", json={"name": "тст-11", "course": 1, "specialty": "126 ІСТ", "curator_id": 2, "subject_ids": [1, 2]})
    assert r.status_code == 201, r.text
    g = r.json()
    assert g["name"] == "ТСТ-11", "назва нормалізується"
    assert sorted(g["subject_ids"]) == [1, 2] and g["curator_name"] == "Петренко Ольга Миколаївна"
    assert len(admin.get(f"/api/groups/{g['id']}/subjects").json()) == 2
    upd = admin.put(f"/api/groups/{g['id']}", json={"name": "ТСТ-21", "course": 2, "specialty": "126 ІСТ", "subject_ids": [3]}).json()
    assert upd["subject_ids"] == [3] and upd["curator_id"] is None
    assert admin.post("/api/groups", json={"name": "тст-21", "course": 2, "specialty": "x"}).status_code == 409
    assert admin.post("/api/groups", json={"name": "X", "course": 9, "specialty": "x"}).status_code == 400
    assert admin.delete(f"/api/groups/{g['id']}").status_code == 204
    assert admin.get(f"/api/groups/{g['id']}").status_code == 404


def test_delete_group_with_students_is_409(admin):
    g = admin.post("/api/groups", json={"name": "DEL-1", "course": 1, "specialty": "x"}).json()
    s = admin.post("/api/students", json={"last_name": "А", "first_name": "Б", "gender": "F", "record_book": "DEL-S", "group_id": g["id"]}).json()
    r = admin.delete(f"/api/groups/{g['id']}")
    assert r.status_code == 409 and "переведіть" in r.json()["error"]
    assert admin.get(f"/api/students/{s['id']}").json()["group_id"] == g["id"]
    # deletable once the student is moved out
    assert admin.patch(f"/api/students/{s['id']}", json={"group_id": None}).status_code == 200
    assert admin.delete(f"/api/groups/{g['id']}").status_code == 204


def test_subject_crud(admin):
    r = admin.post("/api/subjects", json={"name": "Тестова дисципліна", "code": "ТД", "credits": 3.5, "hours": 105,
                                          "semester": 2, "control": "credit", "teacher_id": 3, "group_ids": [1]})
    assert r.status_code == 201
    s = r.json()
    assert s["credits"] == 3.5 and s["group_ids"] == [1]
    bad = admin.put(f"/api/subjects/{s['id']}", json={"name": "X", "credits": 0, "hours": 10, "semester": 1, "control": "oral"})
    assert bad.status_code == 400 and {"credits", "control"} <= bad.json()["details"].keys()
    upd = admin.put(f"/api/subjects/{s['id']}", json={"name": "Нова назва", "credits": 4, "hours": 120, "semester": 3, "control": "exam"}).json()
    assert upd["name"] == "Нова назва" and upd["teacher_id"] is None
    assert admin.post("/api/subjects", json={"name": "вища МАТЕМАТИКА", "credits": 3, "hours": 90, "semester": 1, "control": "exam"}).status_code == 409
    assert admin.delete(f"/api/subjects/{s['id']}").status_code == 204


def test_teacher_catalog_read_only(teacher):
    assert teacher.get("/api/groups").status_code == 200
    assert teacher.post("/api/groups", json={"name": "Z", "course": 1, "specialty": "z"}).status_code == 403
    assert teacher.post("/api/subjects", json={"name": "Z", "credits": 1, "hours": 1, "semester": 1, "control": "exam"}).status_code == 403
    me = teacher.get("/api/auth/me").json()["user"]
    mine = teacher.get("/api/subjects?mine=1").json()
    assert mine and all(s["teacher_id"] == me["id"] for s in mine)


def test_users_admin_only(admin, teacher, make_client):
    assert teacher.get("/api/users").status_code == 403
    assert teacher.get("/api/users/teachers").status_code == 200
    assert all("password_hash" not in u for u in admin.get("/api/users").json())
    r = admin.post("/api/users", json={"username": "NewTeacher", "password": "secret1", "full_name": "Новий Викладач", "role": "teacher"})
    assert r.status_code == 201 and r.json()["username"] == "newteacher"
    make_client("newteacher", "secret1")
    assert admin.post("/api/users", json={"username": "NEWTEACHER", "password": "secret1", "full_name": "X", "role": "teacher"}).status_code == 409
    assert admin.post("/api/users", json={"username": "u 2", "password": "1", "full_name": "X", "role": "boss"}).status_code == 400
    uid = r.json()["id"]
    assert admin.patch(f"/api/users/{uid}", json={"role": "admin", "password": "another1"}).json()["role"] == "admin"
    make_client("newteacher", "another1")
    assert admin.delete(f"/api/users/{uid}").status_code == 204


def test_admin_cannot_demote_or_delete_self(admin):
    me = admin.get("/api/auth/me").json()["user"]
    assert admin.delete(f"/api/users/{me['id']}").status_code == 400
    assert admin.patch(f"/api/users/{me['id']}", json={"role": "teacher"}).status_code == 400
    assert admin.patch(f"/api/users/{me['id']}", json={"is_active": 0}).status_code == 400


def test_delete_teacher_with_history_is_409(admin, db):
    uid = db.execute("SELECT id FROM users WHERE username = 'hrytsenko'").fetchone()["id"]
    r = admin.delete(f"/api/users/{uid}")
    assert r.status_code == 409 and "заблокуйте" in r.json()["error"]
    assert db.execute("SELECT COUNT(*) AS c FROM subjects WHERE teacher_id = ?", (uid,)).fetchone()["c"] > 0
