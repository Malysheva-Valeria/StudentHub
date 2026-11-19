"""Demo data.

    python -m app.seed          — recreate data (asks for confirmation)
    python -m app.seed --yes    — no confirmation
Requires --force in production. On startup, seed_if_empty() seeds only an empty database.
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import sys
import time
from datetime import date, timedelta

from .config import ConfigError, load_settings
from .db import connect, init_db, scalar, transaction
from .migrations import MigrationError
from .security import hash_password
from .utils import local_today

MALE = ["Олександр", "Дмитро", "Максим", "Андрій", "Іван", "Артем", "Назар", "Богдан", "Владислав", "Тарас",
        "Михайло", "Денис", "Євген", "Роман", "Олег", "Ярослав", "Віталій", "Сергій", "Кирило", "Остап"]
FEMALE = ["Анастасія", "Марія", "Софія", "Дарина", "Вікторія", "Олена", "Катерина", "Юлія", "Ірина", "Анна",
          "Христина", "Діана", "Аліна", "Наталія", "Оксана", "Тетяна", "Злата", "Валерія", "Поліна", "Соломія"]
SURNAMES = ["Шевченко", "Коваленко", "Бондаренко", "Ткаченко", "Кравченко", "Олійник", "Шевчук", "Поліщук",
            "Бойко", "Ткачук", "Мельник", "Лисенко", "Мороз", "Савченко", "Руденко", "Марченко", "Петренко", "Гончаренко",
            "Клименко", "Павленко", "Литвиненко", "Кузьменко", "Левченко", "Захарченко", "Романенко", "Гуменюк", "Лук'яненко",
            "Дорошенко", "Савчук", "Пономаренко", "Костенко", "Тимошенко", "Яковенко", "Семенко", "Козак", "Гнатюк",
            "Іваненко", "Єременко", "Ігнатенко"]
MALE_PATR = ["Олександрович", "Іванович", "Петрович", "Миколайович", "Васильович", "Сергійович", "Андрійович", "Володимирович"]
FEMALE_PATR = ["Олександрівна", "Іванівна", "Петрівна", "Миколаївна", "Василівна", "Сергіївна", "Андріївна", "Володимирівна"]

TEACHERS = [
    ("teacher", "Петренко Ольга Миколаївна"),
    ("kovalchuk", "Ковальчук Ігор Васильович"),
    ("moroz", "Мороз Наталія Іванівна"),
    ("sydorenko", "Сидоренко Андрій Петрович"),
    ("lytvyn", "Литвин Світлана Олегівна"),
    ("hrytsenko", "Гриценко Василь Степанович"),
]

GROUPS = [
    ("КН-11", 1, "122 Компʼютерні науки"),
    ("КН-21", 2, "122 Компʼютерні науки"),
    ("КН-31", 3, "122 Компʼютерні науки"),
    ("ІПЗ-21", 2, "121 Інженерія програмного забезпечення"),
    ("ІПЗ-31", 3, "121 Інженерія програмного забезпечення"),
    ("ІПЗ-41", 4, "121 Інженерія програмного забезпечення"),
]

# name, code, credits, hours, semester, control, teacher index, group indexes
SUBJECTS = [
    ("Вища математика", "ВМ", 6, 180, 1, "exam", 3, [0, 1, 3]),
    ("Основи програмування", "ОП", 5, 150, 1, "exam", 0, [0, 1, 3]),
    ("Дискретна математика", "ДМ", 4, 120, 2, "exam", 3, [0, 1, 3]),
    ("Алгоритми та структури даних", "АСД", 5, 150, 3, "exam", 0, [1, 2, 3, 4]),
    ("Бази даних", "БД", 5, 150, 4, "exam", 1, [1, 2, 3, 4, 5]),
    ("Веб-технології", "ВТ", 4, 120, 5, "credit", 1, [2, 4, 5]),
    ("Обʼєктно-орієнтоване програмування", "ООП", 5, 150, 3, "exam", 0, [1, 2, 4]),
    ("Компʼютерні мережі", "КМ", 4, 120, 5, "credit", 4, [2, 4, 5]),
    ("Англійська мова", "АМ", 3, 90, 1, "credit", 2, [0, 1, 2, 3, 4, 5]),
    ("Філософія", "Ф", 3, 90, 2, "credit", 5, [0, 3]),
    ("Проєктування інформаційних систем", "ПІС", 5, 150, 7, "exam", 4, [5]),
]


def study_days(today: date) -> list[date]:
    """Weekdays over the last ~9 months, excluding holidays."""
    days = []
    d = today - timedelta(days=270)
    while d <= today:
        m = d.month
        if d.weekday() < 5 and m not in (7, 8, 1) and not (m == 6 and d.day > 20) and not (m == 12 and d.day > 24):
            days.append(d)
        d += timedelta(days=1)
    return days


def clear_all(conn: sqlite3.Connection) -> None:
    for table in ("attendance", "grades", "group_subjects", "students", "subjects", "groups", "users"):
        conn.execute(f"DELETE FROM {table}")  # noqa: S608 — fixed table list
    conn.execute("DELETE FROM sqlite_sequence")


def seed(conn: sqlite3.Connection, today: date | None = None) -> None:
    today = today or local_today()
    rnd = random.Random(20260901)  # deterministic
    clamp = lambda v, a, b: max(a, min(b, v))  # noqa: E731

    with transaction(conn):
        clear_all(conn)
        conn.execute("INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, 'admin')",
                     ("admin", hash_password("admin123"), "Адміністратор системи"))
        teacher_hash = hash_password("teacher123")
        teacher_ids = [conn.execute(
            "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, 'teacher')",
            (u, teacher_hash, n)).lastrowid for u, n in TEACHERS]

        group_ids = [conn.execute(
            "INSERT INTO groups (name, course, specialty, curator_id) VALUES (?, ?, ?, ?)",
            (n, c, s, teacher_ids[i % len(teacher_ids)])).lastrowid for i, (n, c, s) in enumerate(GROUPS)]

        subjects = []
        for name, code, cr, hours, sem, ctl, ti, gs in SUBJECTS:
            sid = conn.execute(
                "INSERT INTO subjects (name, code, credits, hours, semester, control, teacher_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, code, cr, hours, sem, ctl, teacher_ids[ti])).lastrowid
            conn.executemany("INSERT INTO group_subjects (group_id, subject_id) VALUES (?, ?)", [(group_ids[g], sid) for g in gs])
            subjects.append({"id": sid, "groups": [group_ids[g] for g in gs], "teacher": teacher_ids[ti], "control": ctl})

        students = []
        book = 1
        for gi, (_, course, _) in enumerate(GROUPS):
            enroll_year = (today.year if today.month >= 9 else today.year - 1) - (course - 1)
            for _ in range(22 + rnd.randrange(8)):
                female = rnd.random() < 0.52
                r = rnd.random()
                status = "academic_leave" if r < 0.03 else "expelled" if r < 0.05 else "active"
                record_book = f"{str(enroll_year)[2:]}{book:04d}"
                sid = conn.execute("""
                    INSERT INTO students (last_name, first_name, middle_name, gender, birth_date, email, phone,
                                          record_book, group_id, status, enrolled_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                    rnd.choice(SURNAMES), rnd.choice(FEMALE if female else MALE),
                    rnd.choice(FEMALE_PATR if female else MALE_PATR), "F" if female else "M",
                    f"{enroll_year - 17}-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}",
                    f"st{record_book}@student.edu.ua", f"+38067{rnd.randint(1000000, 9999999)}",
                    record_book, group_ids[gi], status, f"{enroll_year}-09-01")).lastrowid
                book += 1
                students.append({
                    "id": sid, "group": group_ids[gi], "status": status, "enrolled": f"{enroll_year}-09-01",
                    "ability": clamp(76 + (rnd.random() + rnd.random() + rnd.random() - 1.5) * 28, 38, 99),
                    "diligence": clamp(0.94 - (0.25 * rnd.random() + 0.1 if rnd.random() < 0.12 else 0.08 * rnd.random()), 0.45, 0.99),
                })

        days = study_days(today)
        att_rows, grade_rows = [], []
        for sub in subjects:
            for gid in sub["groups"]:
                group_students = [s for s in students if s["group"] == gid and s["status"] == "active"]
                weekday = (sub["id"] * 7 + gid * 3) % 5  # one lesson a week on a fixed weekday
                lessons = [d for d in days if d.weekday() == weekday]
                for li, d in enumerate(lessons):
                    ds = d.isoformat()
                    is_module = li > 0 and li % 8 == 0
                    for st in group_students:
                        if ds < st["enrolled"]:
                            continue
                        if rnd.random() < st["diligence"]:
                            status = "late" if rnd.random() < 0.07 else "present"
                        else:
                            status = "excused" if rnd.random() < 0.3 else "absent"
                        att_rows.append((st["id"], sub["id"], ds, status, sub["teacher"], gid))
                        if status in ("present", "late") and (is_module or rnd.random() < 0.28):
                            value = round(clamp(st["ability"] + (rnd.random() - 0.5) * 22, 20, 100))
                            grade_rows.append((st["id"], sub["id"], value, "module" if is_module else "current", ds, sub["teacher"],
                                               f"{ds} 12:00:00", gid))
                # spring-semester finals (June)
                june = [d for d in lessons if d.month == 6]
                if june:
                    fd = june[-1].isoformat()
                    for st in group_students:
                        if fd >= st["enrolled"]:
                            value = round(clamp(st["ability"] + (rnd.random() - 0.45) * 20, 25, 100))
                            grade_rows.append((st["id"], sub["id"], value, sub["control"], fd, sub["teacher"], f"{fd} 14:00:00", gid))
        conn.executemany("INSERT OR IGNORE INTO attendance (student_id, subject_id, date, status, teacher_id, group_id) "
                         "VALUES (?, ?, ?, ?, ?, ?)", att_rows)
        conn.executemany("INSERT INTO grades (student_id, subject_id, value, type, date, teacher_id, created_at, group_id) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", grade_rows)


def seed_if_empty(db_path: str) -> bool:
    conn = connect(db_path)
    try:
        if scalar(conn, "SELECT COUNT(*) FROM users") == 0:
            seed(conn)
            return True
        return False
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.seed", description="Перестворити демо-дані StudentHub")
    parser.add_argument("--yes", action="store_true", help="не питати підтвердження, якщо в базі вже є дані")
    parser.add_argument("--force", action="store_true", help="дозволити запуск у production (APP_ENV=production)")
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
        init_db(settings.db_path)
    except (ConfigError, MigrationError) as e:
        print(f"Помилка: {e}", file=sys.stderr)
        return 1
    if settings.production and not args.force:
        print("Помилка: APP_ENV=production — демо-дані замінять усі реальні дані. "
              "Якщо ви справді цього хочете, додайте --force", file=sys.stderr)
        return 1
    c = connect(settings.db_path)
    try:
        if scalar(c, "SELECT COUNT(*) FROM users") and not args.yes:
            answer = input(f"У базі {settings.db_path} уже є дані — їх буде ВИДАЛЕНО. Введіть yes, щоб продовжити: ")
            if answer.strip().lower() != "yes":
                print("Скасовано")
                return 1
        t0 = time.perf_counter()
        seed(c)
        n = {t: scalar(c, f"SELECT COUNT(*) FROM {t}") for t in ("students", "grades", "attendance")}  # noqa: S608
    finally:
        c.close()
    print(f"Готово за {time.perf_counter() - t0:.1f} с: студентів {n['students']}, оцінок {n['grades']}, "
          f"записів відвідуваності {n['attendance']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
