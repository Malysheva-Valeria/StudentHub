"""Pydantic schemas for request validation and API responses."""
from __future__ import annotations

from datetime import date
from typing import Annotated, ClassVar, Generic, Literal, TypeVar

from pydantic import (AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints,
                      ValidationInfo, field_validator)

from .constants import DATE_RE, EMAIL_RE, INT_MAX, MAX_PASSWORD_BYTES, MIN_PHONE_DIGITS, PHONE_RE


def _empty_to_none(v):
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    return v


def check_date(v: str) -> str:
    if not DATE_RE.match(v):
        raise ValueError("Дата у форматі РРРР-ММ-ДД")
    try:
        date.fromisoformat(v)
    except ValueError:
        raise ValueError("Дата у форматі РРРР-ММ-ДД") from None
    return v


def _check_email(v: str) -> str:
    if not EMAIL_RE.match(v):
        raise ValueError("Некоректний email")
    return v


def _check_phone(v: str | None) -> str | None:
    if v is not None and (not PHONE_RE.match(v) or sum(ch.isdigit() for ch in v) < MIN_PHONE_DIGITS):
        raise ValueError("Некоректний телефон")
    return v


def _check_password(v: str) -> str:
    if len(v.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError("Пароль задовгий (максимум 72 байти)")
    return v


def Str(max_length: int, min_length: int = 1):  # noqa: N802 — type factory
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=min_length, max_length=max_length)]


def OptStr(max_length: int):  # noqa: N802
    return Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=max_length)] | None,
        BeforeValidator(_empty_to_none),
    ]


IsoDate = Annotated[str, StringConstraints(strip_whitespace=True), AfterValidator(check_date)]
OptDate = Annotated[IsoDate | None, BeforeValidator(_empty_to_none)]
OptEmail = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, max_length=120), AfterValidator(_check_email)] | None,
    BeforeValidator(_empty_to_none),
]
Password = Annotated[str, StringConstraints(min_length=6, max_length=200), AfterValidator(_check_password)]
Id = Annotated[int, Field(ge=1, le=INT_MAX)]
OptId = Annotated[Id | None, BeforeValidator(_empty_to_none)]
RecordBook = Annotated[Str(20), AfterValidator(str.upper)]  # stored uppercase

Role = Literal["admin", "teacher"]
StudentStatus = Literal["active", "academic_leave", "expelled", "graduated"]
GradeType = Literal["current", "module", "exam", "credit"]
AttendanceStatus = Literal["present", "absent", "late", "excused"]
ControlForm = Literal["exam", "credit"]
Gender = Literal["M", "F"]


class Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class PartialModel(Model):
    """PATCH body: only sent fields are applied; REQUIRED fields cannot be null."""

    REQUIRED: ClassVar[tuple[str, ...]] = ()

    @field_validator("*", mode="after")
    @classmethod
    def _required_not_null(cls, v, info: ValidationInfo):
        if v is None and info.field_name in cls.REQUIRED:
            raise ValueError("Обовʼязкове поле")
        return v


# ---------- Auth ----------
class LoginIn(Model):
    username: Str(50)
    password: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class ChangePasswordIn(Model):
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    new_password: Password


# ---------- Users ----------
class UserCreate(Model):
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=50, pattern=r"^[\w.\-]+$")]
    password: Password
    full_name: Str(120)
    role: Role


class UserUpdate(PartialModel):
    REQUIRED: ClassVar[tuple[str, ...]] = ("full_name", "role", "is_active")
    full_name: Str(120) | None = None
    role: Role | None = None
    is_active: bool | None = None
    password: Annotated[Password | None, BeforeValidator(_empty_to_none)] = None


# ---------- Groups ----------
class GroupIn(Model):
    name: Str(30)
    course: Annotated[int, Field(ge=1, le=6)]
    specialty: Str(150)
    curator_id: OptId = None
    subject_ids: Annotated[list[Id], Field(max_length=500)] | None = None


# ---------- Subjects ----------
class SubjectIn(Model):
    name: Str(150)
    code: OptStr(20) = None
    credits: Annotated[float, Field(ge=0.5, le=30)]
    hours: Annotated[int, Field(ge=1, le=1000)]
    semester: Annotated[int, Field(ge=1, le=12)]
    control: ControlForm
    teacher_id: OptId = None
    group_ids: Annotated[list[Id], Field(max_length=500)] | None = None


# ---------- Students ----------
Phone = Annotated[OptStr(30), AfterValidator(_check_phone)]


class StudentBase(Model):
    middle_name: OptStr(60) = None
    birth_date: OptDate = None
    email: OptEmail = None
    phone: Phone = None
    group_id: OptId = None
    enrolled_at: OptDate = None


class StudentCreate(StudentBase):
    last_name: Str(60)
    first_name: Str(60)
    gender: Gender
    record_book: RecordBook
    status: StudentStatus = "active"


class StudentUpdate(StudentBase, PartialModel):
    REQUIRED: ClassVar[tuple[str, ...]] = ("last_name", "first_name", "gender", "record_book", "status", "enrolled_at")
    last_name: Str(60) | None = None
    first_name: Str(60) | None = None
    gender: Gender | None = None
    record_book: RecordBook | None = None
    status: StudentStatus | None = None


# ---------- Grades ----------
GradeValue = Annotated[int, Field(ge=0, le=100, strict=True)]


class GradeCreate(Model):
    student_id: Id
    subject_id: Id
    value: GradeValue
    type: GradeType
    date: IsoDate
    comment: OptStr(300) = None


class GradeUpdate(PartialModel):
    REQUIRED: ClassVar[tuple[str, ...]] = ("value", "type", "date")
    value: GradeValue | None = None
    type: GradeType | None = None
    date: IsoDate | None = None
    comment: OptStr(300) = None


class BulkGradeRecord(Model):
    student_id: Id
    value: Annotated[GradeValue | None, BeforeValidator(_empty_to_none)] = None


class GradeBulk(Model):
    subject_id: Id
    type: GradeType
    date: IsoDate
    records: Annotated[list[BulkGradeRecord], Field(min_length=1, max_length=500)]


# ---------- Attendance ----------
class AttendanceRecord(Model):
    student_id: Id
    status: AttendanceStatus


class AttendanceBulk(Model):
    subject_id: Id
    date: IsoDate
    records: Annotated[list[AttendanceRecord], Field(min_length=1, max_length=500)]


# =====================================================================================
# API responses. response_model drops unlisted fields (e.g. password_hash).
# =====================================================================================
T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    limit: int
    pages: int


class EctsOut(BaseModel):
    min: int
    ects: str
    national: str


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    role: Role
    is_active: int
    created_at: str


class UserBrief(BaseModel):
    id: int
    full_name: str
    is_active: int | None = None  # admin only


class GroupOut(BaseModel):
    id: int
    name: str
    course: int
    specialty: str
    curator_id: int | None
    curator_name: str | None
    created_at: str
    students_count: int
    avg_grade: float | None


class GroupDetail(GroupOut):
    subject_ids: list[int]


class SubjectOut(BaseModel):
    id: int
    name: str
    code: str | None
    credits: float
    hours: int
    semester: int
    control: ControlForm
    teacher_id: int | None
    teacher_name: str | None
    created_at: str
    avg_grade: float | None
    groups_count: int


class SubjectDetail(SubjectOut):
    group_ids: list[int]


class StudentOut(BaseModel):
    id: int
    last_name: str
    first_name: str
    middle_name: str | None
    gender: Gender
    birth_date: str | None   # null for teachers
    email: str | None
    phone: str | None        # null for teachers
    record_book: str
    group_id: int | None
    group_name: str | None
    status: StudentStatus
    enrolled_at: str
    created_at: str
    avg_grade: float | None
    attendance_rate: float | None


class GradeOut(BaseModel):
    id: int
    student_id: int
    subject_id: int
    value: int
    type: GradeType
    date: str
    comment: str | None
    teacher_id: int | None
    created_at: str
    subject_name: str
    group_id: int | None
    group_name: str | None
    student_name: str
    teacher_name: str | None
    ects: str | None


class GradeDetail(GradeOut):
    ects: EctsOut | None  # type: ignore[assignment]  # full ECTS entry for a single grade


class GradePage(Page[GradeOut]):
    avg: float | None
