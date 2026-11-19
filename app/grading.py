"""Grading scale and shared metric definitions (also registered as SQLite functions).

* Student average: mean of all grades, rounded half-up to 0.1.
* Group/overall average: mean of active students' averages.
* Subject average: mean of active students' per-subject averages.
* Bucket: by ECTS letter (A excellent, B-C good, D-E satisfactory, FX-F failing).
* Attendance: (present + late) / total * 100, rounded to 0.1.
"""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, TypedDict


class EctsGrade(TypedDict):
    min: int
    ects: str
    national: str


ECTS: list[EctsGrade] = [
    {"min": 90, "ects": "A", "national": "Відмінно"},
    {"min": 82, "ects": "B", "national": "Добре"},
    {"min": 74, "ects": "C", "national": "Добре"},
    {"min": 64, "ects": "D", "national": "Задовільно"},
    {"min": 60, "ects": "E", "national": "Задовільно"},
    {"min": 35, "ects": "FX", "national": "Незадовільно"},
    {"min": 0, "ects": "F", "national": "Незадовільно"},
]

Bucket = Literal["excellent", "good", "satisfactory", "failing"]
BUCKETS: dict[str, Bucket] = {
    "A": "excellent", "B": "good", "C": "good", "D": "satisfactory", "E": "satisfactory", "FX": "failing", "F": "failing",
}
FAILING_LETTERS = ("FX", "F")


def _half_up(value: float, places: str) -> Decimal:
    # repr() gives the shortest decimal form, so 73.45 rounds to 73.5, not 73.4
    return Decimal(repr(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def round_half_up(value: float) -> int:
    """Round half up to int (89.5 -> 90), unlike banker's round()."""
    return int(_half_up(float(value), "1"))


def round1(value: float | None) -> float | None:
    """Round half up to 0.1. Registered in SQLite as round1()."""
    return None if value is None else float(_half_up(float(value), "0.1"))


def avg1(values: list[float]) -> float | None:
    """Mean rounded to 0.1; fsum makes it order-independent."""
    if not values:
        return None
    return round1(math.fsum(values) / len(values))


def to_ects(score: float | None) -> EctsGrade | None:
    if score is None:
        return None
    s = round_half_up(float(score))
    return next((r for r in ECTS if s >= r["min"]), ECTS[-1])


def ects_letter(score: float | None) -> str | None:
    e = to_ects(score)
    return e["ects"] if e else None


def bucket(score: float | None) -> Bucket | None:
    """Performance bucket by ECTS letter."""
    letter = ects_letter(score)
    return BUCKETS[letter] if letter else None


def is_passing(score: float | None) -> bool:
    """Passing: ECTS letter is not FX/F (rounded score >= 60)."""
    letter = ects_letter(score)
    return letter is not None and letter not in FAILING_LETTERS


def attendance_rate(present: int | None, late: int | None, total: int | None) -> float | None:
    """Attendance % counting present and late. Registered in SQLite as attendance_rate()."""
    if not total:
        return None
    return round1(((present or 0) + (late or 0)) / total * 100)


def percent(part: int, whole: int) -> float | None:
    return round1(part / whole * 100) if whole else None
