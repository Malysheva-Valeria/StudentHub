import pytest


@pytest.fixture(scope="module")
def ctx(db):
    teacher_id = db.execute("SELECT id FROM users WHERE username='teacher'").fetchone()["id"]
    own = db.execute("SELECT * FROM subjects WHERE teacher_id = ? LIMIT 1", (teacher_id,)).fetchone()
    foreign = db.execute("SELECT * FROM subjects WHERE teacher_id != ? LIMIT 1", (teacher_id,)).fetchone()
    gid = db.execute("SELECT group_id FROM group_subjects WHERE subject_id = ? LIMIT 1", (own["id"],)).fetchone()["group_id"]
    student = db.execute("SELECT * FROM students WHERE group_id = ? AND status='active' LIMIT 1", (gid,)).fetchone()
    return {"teacher_id": teacher_id, "own": own, "foreign": foreign, "student": student}


def test_teacher_grade_lifecycle(teacher, ctx, today):
    r = teacher.post("/api/grades", json={"student_id": ctx["student"]["id"], "subject_id": ctx["own"]["id"], "value": 91,
                                          "type": "current", "date": today, "comment": "Відмінна робота"})
    assert r.status_code == 201, r.text
    g = r.json()
    assert g["ects"]["ects"] == "A" and g["teacher_id"] == ctx["teacher_id"]
    upd = teacher.patch(f"/api/grades/{g['id']}", json={"value": 59}).json()
    assert upd["ects"]["ects"] == "FX" and upd["comment"] == "Відмінна робота"
    assert teacher.delete(f"/api/grades/{g['id']}").status_code == 204
    assert teacher.get(f"/api/grades/{g['id']}").status_code == 404


def test_teacher_cannot_touch_foreign_subject(teacher, ctx, db, today):
    body = {"student_id": ctx["student"]["id"], "subject_id": ctx["foreign"]["id"], "value": 80, "type": "current", "date": today}
    assert teacher.post("/api/grades", json=body).status_code == 403
    # foreign subject's grade in the teacher's group: visible but read-only
    gid = db.execute("SELECT id FROM grades WHERE subject_id = ? AND group_id = ? LIMIT 1",
                     (ctx["foreign"]["id"], ctx["student"]["group_id"])).fetchone()["id"]
    assert teacher.patch(f"/api/grades/{gid}", json={"value": 100}).status_code == 403
    assert teacher.delete(f"/api/grades/{gid}").status_code == 403
    att = {"subject_id": ctx["foreign"]["id"], "date": today, "records": [{"student_id": ctx["student"]["id"], "status": "present"}]}
    assert teacher.post("/api/attendance/bulk", json=att).status_code == 403
    bulk = {"subject_id": ctx["foreign"]["id"], "type": "current", "date": today, "records": [{"student_id": ctx["student"]["id"], "value": 90}]}
    assert teacher.post("/api/grades/bulk", json=bulk).status_code == 403


def test_admin_any_subject(admin, ctx, today):
    r = admin.post("/api/grades", json={"student_id": ctx["student"]["id"], "subject_id": ctx["foreign"]["id"], "value": 75, "type": "module", "date": today})
    assert r.status_code == 201


@pytest.mark.parametrize("patch,field", [
    ({"value": 101}, "value"), ({"value": -1}, "value"), ({"value": 50.5}, "value"), ({"value": "80"}, "value"),
    ({"type": "oral"}, "type"), ({"date": "2026-13-01"}, "date"),
])
def test_grade_validation(admin, ctx, today, patch, field):
    body = {"student_id": ctx["student"]["id"], "subject_id": ctx["own"]["id"], "value": 80, "type": "current", "date": today, **patch}
    r = admin.post("/api/grades", json=body)
    assert r.status_code == 400 and field in r.json()["details"]


def test_grade_business_rules(admin, ctx, today):
    base = {"student_id": ctx["student"]["id"], "subject_id": ctx["own"]["id"], "value": 80, "type": "current", "date": today}
    assert admin.post("/api/grades", json={**base, "date": "2099-01-01"}).status_code == 400
    assert admin.post("/api/grades", json={**base, "student_id": 999999}).status_code == 400
    assert admin.post("/api/grades", json={**base, "subject_id": 999999}).status_code == 404


def test_bulk_and_journal(teacher, ctx, db, today):
    sids = [r["id"] for r in db.execute("SELECT id FROM students WHERE group_id = ? AND status='active' ORDER BY id", (ctx["student"]["group_id"],))]
    records = [{"student_id": s, "value": 70 + i} for i, s in enumerate(sids[:3])] + [{"student_id": sids[3], "value": ""}]
    r = teacher.post("/api/grades/bulk", json={"subject_id": ctx["own"]["id"], "type": "module", "date": today, "records": records})
    assert r.status_code == 201 and r.json()["saved"] == 3

    assert teacher.post("/api/grades/bulk", json={"subject_id": ctx["own"]["id"], "type": "module", "date": today,
                                                  "records": [{"student_id": sids[0], "value": 500}]}).status_code == 400
    before = db.execute("SELECT COUNT(*) AS c FROM grades").fetchone()["c"]
    r = teacher.post("/api/grades/bulk", json={"subject_id": ctx["own"]["id"], "type": "current", "date": today,
                                               "records": [{"student_id": sids[0], "value": 80}, {"student_id": 999999, "value": 80}]})
    assert r.status_code == 400
    assert db.execute("SELECT COUNT(*) AS c FROM grades").fetchone()["c"] == before, "транзакцію відкочено"

    j = teacher.get(f"/api/grades/journal?group_id={ctx['student']['group_id']}&subject_id={ctx['own']['id']}").json()
    key = f"{today}|module"
    assert any(c["key"] == key for c in j["columns"])
    row = next(r for r in j["rows"] if r["id"] == sids[0])
    assert row["cells"][key]["value"] == 70
    assert teacher.get("/api/grades/journal").status_code == 400


def test_grade_filters(admin, ctx):
    r = admin.get(f"/api/grades?subject_id={ctx['own']['id']}&type=module&from=2026-01-01&limit=500").json()
    assert r["items"] and all(g["subject_id"] == ctx["own"]["id"] and g["type"] == "module" and g["date"] >= "2026-01-01" for g in r["items"])
    assert r["avg"] > 0
    gid = ctx["student"]["group_id"]
    assert all(g["group_id"] == gid for g in admin.get(f"/api/grades?group_id={gid}&limit=50").json()["items"])
    found = admin.get("/api/grades", params={"search": ctx["student"]["last_name"].lower(), "limit": 5}).json()["items"]
    assert found and all(g["student_name"].lower().startswith(ctx["student"]["last_name"].lower()) for g in found)


def test_attendance_sheet_upsert(teacher, ctx, db, today):
    q = f"/api/attendance/sheet?group_id={ctx['student']['group_id']}&subject_id={ctx['own']['id']}&date={today}"
    sheet = teacher.get(q).json()
    records = [{"student_id": r["student_id"], "status": "absent" if i == 0 else "present"} for i, r in enumerate(sheet["rows"])]
    r = teacher.post("/api/attendance/bulk", json={"subject_id": ctx["own"]["id"], "date": today, "records": records})
    assert r.status_code == 200 and r.json()["saved"] == len(records)
    records[0]["status"] = "excused"
    teacher.post("/api/attendance/bulk", json={"subject_id": ctx["own"]["id"], "date": today, "records": records})
    again = teacher.get(q).json()
    assert again["marked"] and again["rows"][0]["status"] == "excused"
    c = db.execute("SELECT COUNT(*) AS c FROM attendance WHERE subject_id=? AND date=? AND student_id=?",
                   (ctx["own"]["id"], today, records[0]["student_id"])).fetchone()["c"]
    assert c == 1


def test_attendance_validation(teacher, ctx, today):
    assert teacher.get("/api/attendance/sheet?group_id=1").status_code == 400
    sid = ctx["student"]["id"]
    own = ctx["own"]["id"]
    assert teacher.post("/api/attendance/bulk", json={"subject_id": own, "date": today, "records": [{"student_id": sid, "status": "sleeping"}]}).status_code == 400
    assert teacher.post("/api/attendance/bulk", json={"subject_id": own, "date": "2099-01-01", "records": [{"student_id": sid, "status": "present"}]}).status_code == 400
    assert teacher.post("/api/attendance/bulk", json={"subject_id": own, "date": today, "records": []}).status_code == 400
    assert teacher.post("/api/attendance/bulk", json={"subject_id": own, "date": today, "records": [{"student_id": 999999, "status": "present"}]}).status_code == 400


def test_attendance_summary_rate(admin, ctx, db):
    rows = admin.get(f"/api/attendance/summary?group_id={ctx['student']['group_id']}").json()
    row = next(r for r in rows if r["student_id"] == ctx["student"]["id"])
    raw = db.execute("SELECT COUNT(*) AS t, SUM(status IN ('present','late')) AS p FROM attendance WHERE student_id = ?", (ctx["student"]["id"],)).fetchone()
    assert row["total"] == raw["t"]
    assert row["rate"] == pytest.approx(raw["p"] / raw["t"] * 100, abs=0.051)
