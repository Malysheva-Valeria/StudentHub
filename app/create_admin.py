"""Create an admin or reset an existing admin's password.

    python -m app.create_admin                                   # interactive
    python -m app.create_admin --username admin --password '…'   # non-interactive
"""
from __future__ import annotations

import argparse
import getpass
import sqlite3
import sys

from .config import ConfigError, load_settings
from .constants import MAX_PASSWORD_BYTES, MIN_ADMIN_PASSWORD
from .db import connect, init_db, one, transaction
from .migrations import MigrationError
from .security import delete_user_sessions, hash_password, normalize_username


class AdminError(ValueError):
    """Invalid admin input."""


def check_admin_password(password: str) -> None:
    if len(password.strip()) < MIN_ADMIN_PASSWORD:
        raise AdminError(f"Пароль занадто короткий: мінімум {MIN_ADMIN_PASSWORD} символів")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise AdminError(f"Пароль задовгий: максимум {MAX_PASSWORD_BYTES} байти")


def create_or_update_admin(db: sqlite3.Connection, username: str, password: str, full_name: str) -> str:
    """Create an admin or reset its password (reactivates it, ends its sessions); return "created" or "updated"."""
    username = normalize_username(username)
    if not username:
        raise AdminError("Вкажіть логін")
    check_admin_password(password)
    password_hash = hash_password(password)
    with transaction(db):
        user = one(db, "SELECT id, role FROM users WHERE username = ?", (username,))
        if user is None:
            db.execute("INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, 'admin')",
                       (username, password_hash, full_name))
            return "created"
        if user["role"] != "admin":
            raise AdminError(f"Користувач «{username}» не є адміністратором — команда змінює лише адміністраторів")
        db.execute("UPDATE users SET password_hash = ?, is_active = 1 WHERE id = ?", (password_hash, user["id"]))
        delete_user_sessions(db, user["id"])
        return "updated"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.create_admin", description="Створити адміністратора StudentHub")
    parser.add_argument("--username", help="логін адміністратора")
    parser.add_argument("--password", help="пароль (не менше 8 символів); якщо не вказано — буде запитано")
    parser.add_argument("--full-name", default="Адміністратор системи", help="ПІБ")
    args = parser.parse_args(argv)

    username = args.username or input("Логін адміністратора: ")
    password = args.password
    if password is None:
        password = getpass.getpass("Пароль (мін. 8 символів): ")
        if getpass.getpass("Повторіть пароль: ") != password:
            print("Помилка: паролі не збігаються", file=sys.stderr)
            return 1
    try:
        settings = load_settings()
        init_db(settings.db_path)
        db = connect(settings.db_path)
        try:
            result = create_or_update_admin(db, username, password, args.full_name)
        finally:
            db.close()
    except (AdminError, ConfigError, MigrationError) as e:
        print(f"Помилка: {e}", file=sys.stderr)
        return 1
    print("Адміністратора створено" if result == "created" else "Пароль адміністратора змінено, його сесії завершено")
    return 0


if __name__ == "__main__":
    sys.exit(main())
