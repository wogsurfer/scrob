"""The download pipeline's health, for the dashboard."""

from fastapi import APIRouter, Depends, Query

from core.pipeline import pipeline_health
from dependencies import get_current_user
from models.users import User

router = APIRouter()


@router.get("/health")
async def health(
    refresh: bool = Query(False),
    current_user: User = Depends(get_current_user),
):
    """Whether Sonarr, Radarr, Prowlarr and Unpackerr are working, with any
    problems found. Cached for two minutes unless `refresh`."""
    return await pipeline_health(force=refresh)
