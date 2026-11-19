"""Domain constants and limits."""
from __future__ import annotations

import re

MAX_PASSWORD_BYTES = 72          # bcrypt input limit
MAX_BODY_BYTES = 1024 * 1024     # max request body (1 MB)
INT_MAX = 2**63 - 1              # SQLite INTEGER max

# Failed login attempts per 15 min, keyed by login+IP, login, and IP
LOGIN_LIMITS = {"user_ip": 10, "user": 100, "ip": 50}
PASSWORD_CHANGE_LIMITS = {"user": 5}   # failed password change attempts
MIN_ADMIN_PASSWORD = 8                 # min password length for create_admin

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PHONE_RE = re.compile(r"^[+\d\s()\-]{5,30}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

MIN_DATE = "2000-01-01"          # earliest lesson/enrollment date
MIN_BIRTH_DATE = "1900-01-01"
MIN_PHONE_DIGITS = 7

PASS_SCORE = 60                  # min passing score
LOW_ATTENDANCE = 75              # attendance % below this is at-risk

FINAL_TYPES = ("exam", "credit")  # final assessment types
GRADE_TYPES = ("current", "module", "exam", "credit")
STUDENT_STATUSES = ("active", "academic_leave", "expelled", "graduated")
STATUS_UA = {"active": "Навчається", "academic_leave": "Академвідпустка", "expelled": "Відрахований", "graduated": "Випускник"}
CONTROL_UA = {"exam": "екзамен", "credit": "залік"}

# Apostrophe variants treated as equal in search
APOSTROPHES = "'ʼ’`"
