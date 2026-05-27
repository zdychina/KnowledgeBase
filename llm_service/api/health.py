from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    """Health check including database connectivity."""
    db = request.app.state.db
    db_health = await db.health_check()
    return {
        "status": "ok" if db_health.get("connected") and db_health.get("tables_ok") else "degraded",
        "database": db_health,
    }
