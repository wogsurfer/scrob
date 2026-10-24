from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core import soundtrack as soundtrack_core
from db import get_db
from dependencies import get_current_user
from models.users import User
from routers.media import get_user_tmdb_key

router = APIRouter()


@router.get("/{kind}/{tmdb_id}")
async def get_soundtrack(
    kind: Literal["movie", "tv"],
    tmdb_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The songs on a film's or show's soundtrack albums (score and dialogue left out)."""
    tmdb_key = await get_user_tmdb_key(db, current_user.id)
    return {"tmdb_id": tmdb_id, **await soundtrack_core.soundtrack(kind, tmdb_id, tmdb_key)}
