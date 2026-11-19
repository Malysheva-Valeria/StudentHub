from __future__ import annotations

from fastapi import APIRouter

from ..deps import Db, UserScope
from ..stats import dashboard as build_dashboard
from ..utils import local_today

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(scope: UserScope, db: Db):
    """Dashboard data, limited to the teacher's groups."""
    return build_dashboard(db, scope, local_today())
