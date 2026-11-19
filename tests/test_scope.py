"""Teacher scope: only students of groups that study the teacher's subjects or that the teacher curates."""
import pytest



@pytest.fixture(scope="module")
def scope(db):
    tid = db.execute("SELECT id FROM users WHERE username = 'teacher'").fetchone()["id"]
    groups = {r["group_id"] for r in db.execute("""
        SELECT gs.group_id FROM group_subjects gs JOIN subjects sb ON sb.id = gs.subject_id WHERE sb.teacher_id = ?
        UNION SELECT id FROM groups WHERE curator_id = ?""", (tid, tid))}
    outside_group = db.execute(f"SELECT id FROM groups WHERE id NOT IN ({','.join(map(str, groups))}) LIMIT 1").fetchone()["id"]
    inside = db.execute(f"SELECT id FROM students WHERE group_id IN ({','.join(map(str, groups))}) LIMIT 1").fetchone()["id"]
    outside = db.execute("SELECT id FROM students WHERE group_id = ? LIMIT 1", (outside_group,)).fetchone()["id"]
    return {"groups": groups, "outside_group": outside_group, "inside": inside, "outside": outside}


def student_group(db, sid):
    return db.execute("SELECT group_id FROM students WHERE id = ?", (sid,)).fetchone()["group_id"]


def test_student_list_scoped_and_private_fields_hidden(teacher, scope, db):
    r = teacher.get("/api/students?limit=500").json()
    assert r["items"] and {s["group_id"] for s in r["items"]} <= scope["groups"]
    expected = db.execute(f"SELECT COUNT(*) AS c FROM students WHERE group_id IN ({','.join(map(str, scope['groups']))})").fetchone()["c"]
    assert r["total"] == expected
    assert all(s["birth_date"] is None and s["phone"] is None for s in r["items"])
    assert any(s["email"] for s in r["items"]), "email лишається"
    assert teacher.get(f"/api/students?group_id={scope['outside_group']}").json()["total"] == 0


def test_admin_sees_everything(admin, scope):
    card = admin.get(f"/api/students/{scope['outside']}").json()
    assert card["birth_date"] and card["phone"]


def test_card_outside_scope_is_404(teacher, scope):
    assert teacher.get(f"/api/students/{scope['outside']}").status_code == 404
    card = teacher.get(f"/api/students/{scope['inside']}")
    assert card.status_code == 200 and card.json()["birth_date"] is None and card.json()["phone"] is None


def test_search_scoped(teacher, scope, db):
    last = db.execute("SELECT last_name FROM students WHERE id = ?", (scope["outside"],)).fetchone()["last_name"]
    found = teacher.get("/api/students", params={"search": last, "limit": 500}).json()["items"]
    assert scope["outside"] not in {s["id"] for s in found}


def test_grades_scoped(teacher, scope, db):
    items = teacher.get("/api/grades?limit=500").json()["items"]
    assert items and {g["group_id"] for g in items} <= scope["groups"]
    gid = db.execute("SELECT id FROM grades WHERE student_id = ? LIMIT 1", (scope["outside"],)).fetchone()
    if gid:
        assert teacher.get(f"/api/grades/{gid['id']}").status_code == 404
    assert teacher.get(f"/api/grades?student_id={scope['outside']}").json()["total"] == 0


def test_journal_and_sheet_outside_scope_404(teacher, scope, today):
    g = scope["outside_group"]
    assert teacher.get(f"/api/grades/journal?group_id={g}&subject_id=1").status_code == 404
    assert teacher.get(f"/api/attendance/sheet?group_id={g}&subject_id=1&date={today}").status_code == 404
    rows = teacher.get(f"/api/attendance/summary?group_id={g}").json()
    assert rows == []


def test_reports_scoped(teacher, scope, db):
    names = {r["name"] for r in db.execute(f"SELECT name FROM groups WHERE id IN ({','.join(map(str, scope['groups']))})")}
    perf = teacher.get("/api/reports/performance").json()["items"]
    assert perf and {i["group_name"] for i in perf} <= names
    att = teacher.get("/api/reports/attendance").json()["items"]
    assert att and {i["group_name"] for i in att} <= names
    assert {g["id"] for g in teacher.get("/api/reports/groups").json()} == scope["groups"]
    csv = teacher.get("/api/reports/performance?format=csv").content.decode("utf-8-sig")
    outside_name = db.execute("SELECT name FROM groups WHERE id = ?", (scope["outside_group"],)).fetchone()["name"]
    assert f";{outside_name};" not in csv


def test_dashboard_scoped(teacher, admin, scope, db):
    d = teacher.get("/api/dashboard").json()
    assert {g["id"] for g in d["by_group"]} == scope["groups"] and d["kpi"]["groups"] == len(scope["groups"])
    for key in ("top_students", "at_risk"):
        assert all(student_group(db, s["id"]) in scope["groups"] for s in d[key]), key
    for g in d["recent_grades"]:
        sid = db.execute("SELECT student_id FROM grades WHERE id = ?", (g["id"],)).fetchone()["student_id"]
        assert student_group(db, sid) in scope["groups"]
    assert d["kpi"]["total_students"] < admin.get("/api/dashboard").json()["kpi"]["total_students"]
    # aggregates are scoped and match the teacher's report
    assert d["kpi"]["avg_grade"] == teacher.get("/api/reports/performance").json()["summary"]["avg_grade"]


def test_export_admin_only(teacher, admin):
    assert teacher.get("/api/students/export").status_code == 403
    assert admin.get("/api/students/export").status_code == 200


def test_curator_without_subjects_sees_own_group(admin, make_client, db):
    u = admin.post("/api/users", json={"username": "curator1", "password": "secret1", "full_name": "Куратор Тест", "role": "teacher"}).json()
    g = admin.post("/api/groups", json={"name": "CUR-1", "course": 1, "specialty": "x", "curator_id": u["id"]}).json()
    admin.post("/api/students", json={"last_name": "Кур", "first_name": "Ат", "gender": "M", "record_book": "CUR-S1", "group_id": g["id"]})
    c = make_client("curator1", "secret1")
    items = c.get("/api/students").json()["items"]
    assert [s["record_book"] for s in items] == ["CUR-S1"]
    assert c.get("/api/dashboard").json()["kpi"]["total_students"] == 1


def test_groups_scoped_for_teacher(teacher, admin, scope):
    assert {g["id"] for g in teacher.get("/api/groups").json()} == scope["groups"]
    assert len(admin.get("/api/groups").json()) > len(scope["groups"])
    g = scope["outside_group"]
    for url in (f"/api/groups/{g}", f"/api/groups/{g}/subjects"):
        assert teacher.get(url).status_code == 404, url
        assert admin.get(url).status_code == 200, url
    inside = next(iter(scope["groups"]))
    assert teacher.get(f"/api/groups/{inside}").status_code == 200


def test_teachers_list_minimal_for_teacher(teacher, admin, db):
    blocked = admin.post("/api/users", json={"username": "blocked_t", "password": "secret1", "full_name": "Заблокований Т",
                                             "role": "teacher"}).json()
    admin.patch(f"/api/users/{blocked['id']}", json={"is_active": False})
    items = teacher.get("/api/users/teachers").json()
    assert items and all(set(i) == {"id", "full_name"} for i in items), "лише id та ПІБ"
    assert blocked["id"] not in {i["id"] for i in items}, "заблокованих викладач не бачить"
    active = db.execute("SELECT COUNT(*) AS c FROM users WHERE is_active = 1").fetchone()["c"]
    assert len(items) == active
    full = admin.get("/api/users/teachers").json()
    assert any(i["id"] == blocked["id"] and i["is_active"] == 0 for i in full)


def test_subjects_scoped_to_teacher_groups(teacher, admin, scope, db):
    """Teacher sees only subjects of their groups or that they teach; others are 404."""
    tid = db.execute("SELECT id FROM users WHERE username = 'teacher'").fetchone()["id"]
    groups = ",".join(map(str, scope["groups"]))
    visible = {r["id"] for r in db.execute(f"""
        SELECT subject_id AS id FROM group_subjects WHERE group_id IN ({groups})
        UNION SELECT id FROM subjects WHERE teacher_id = ?""", (tid,))}
    listed = {s["id"] for s in teacher.get("/api/subjects").json()}
    assert listed == visible
    hidden = db.execute(f"SELECT id FROM subjects WHERE id NOT IN ({','.join(map(str, visible))}) LIMIT 1").fetchone()
    if hidden:
        assert teacher.get(f"/api/subjects/{hidden['id']}").status_code == 404
        assert admin.get(f"/api/subjects/{hidden['id']}").status_code == 200
    detail = teacher.get(f"/api/subjects/{next(iter(visible))}").json()
    assert set(detail["group_ids"]) <= scope["groups"]


def test_subject_average_counts_only_teacher_students(teacher, scope, db):
    from app.grading import avg1
    groups = ",".join(map(str, scope["groups"]))
    for s in teacher.get("/api/subjects").json():
        rows = db.execute(f"""
            SELECT round1(AVG(gr.value)) AS a FROM grades gr JOIN students st ON st.id = gr.student_id
            WHERE gr.subject_id = ? AND st.status = 'active' AND st.group_id IN ({groups})
            GROUP BY gr.student_id""", (s["id"],)).fetchall()
        assert s["avg_grade"] == avg1([r["a"] for r in rows])


def test_dashboard_teachers_kpi_scoped(teacher, admin, db):
    total = db.execute("SELECT COUNT(*) AS c FROM users WHERE role = 'teacher' AND is_active = 1").fetchone()["c"]
    assert admin.get("/api/dashboard").json()["kpi"]["teachers"] == total
    assert teacher.get("/api/dashboard").json()["kpi"]["teachers"] <= total
