from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from ..csv_export import csv_response
from ..deps import Db, QueryDate, QueryId, UserScope
from ..stats import Filters, attendance, groups_report, performance

router = APIRouter(prefix="/api/reports", tags=["reports"])

Format = Literal["json", "csv"]


def filters(
    group_id: QueryId = None, subject_id: QueryId = None,
    date_from: Annotated[QueryDate, Query(alias="from")] = None, date_to: Annotated[QueryDate, Query(alias="to")] = None,
) -> Filters:
    return Filters(group_id, subject_id, date_from, date_to)


ReportFilters = Annotated[Filters, Depends(filters)]


@router.get("/performance")
def performance_report(scope: UserScope, db: Db, f: ReportFilters, format: Format = "json"):  # noqa: A002
    data = performance(db, scope, f)
    if format == "csv":
        return csv_response("performance-report.csv", data["items"], [
            ("record_book", "Залікова"), ("student_name", "Студент"), ("group_name", "Група"),
            ("grades_count", "К-сть оцінок"), ("avg_grade", "Середній бал"), ("min_grade", "Мін."),
            ("max_grade", "Макс."), ("ects", "ECTS"), ("national", "Нац. шкала"), ("debts", "Борги"),
        ])
    return data


@router.get("/attendance")
def attendance_report(scope: UserScope, db: Db, f: ReportFilters, format: Format = "json"):  # noqa: A002
    data = attendance(db, scope, f)
    if format == "csv":
        return csv_response("attendance-report.csv", data["items"], [
            ("record_book", "Залікова"), ("student_name", "Студент"), ("group_name", "Група"), ("total", "Занять"),
            ("present", "Присутній"), ("late", "Запізнення"), ("absent", "Пропуск"),
            ("excused", "Поважна причина"), ("rate", "Відвідуваність, %"),
        ])
    return data


@router.get("/groups")
def groups_comparison(scope: UserScope, db: Db, f: ReportFilters, format: Format = "json"):  # noqa: A002
    items = groups_report(db, scope, f)
    if format == "csv":
        return csv_response("groups-report.csv", items, [
            ("name", "Група"), ("course", "Курс"), ("specialty", "Спеціальність"), ("students", "Студентів"),
            ("avg_grade", "Середній бал"), ("attendance_rate", "Відвідуваність, %"),
        ])
    return items
