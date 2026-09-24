"""Read-only FastAPI surface for the Hermes Bill desktop plugin."""

from __future__ import annotations

import sys
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Response

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from bill_store import BillStore, BillValidationError  # noqa: E402


router = APIRouter()


@router.get("/overview")
def overview(
    response: Response,
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
):
    response.headers["Cache-Control"] = "no-store"
    try:
        return BillStore().overview(year=year, month=month)
    except BillValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail="账单数据库暂时不可用") from exc
