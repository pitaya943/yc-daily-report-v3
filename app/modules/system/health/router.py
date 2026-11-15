"""冒煙用端點：證明「HTTP 請求 → 應用程式 → 資料庫」整條路通。"""
from fastapi import APIRouter, Depends

from app.core.clock import clock
from app.core.db import get_db

router = APIRouter()


@router.get("/health")
def health(db=Depends(get_db)) -> dict:
    with db.cursor() as cur:
        cur.execute("select count(*) from yc_v3.accounts")
        accounts = cur.fetchone()[0]
    return {"status": "ok", "accounts": accounts, "now": clock.now().isoformat()}
