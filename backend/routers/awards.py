from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core import awards as awards_core
from db import get_db
from dependencies import get_current_user
from models.users import User
from routers.media import get_user_tmdb_key
from routers.shows import get_user_tvdb_key

router = APIRouter()


async def _keys(db: AsyncSession, user: User) -> tuple[str, str | None]:
    tvdb_key = await get_user_tvdb_key(db, user.id)
    if not tvdb_key:
        raise HTTPException(status_code=400, detail="TVDB API key not configured")
    return tvdb_key, await get_user_tmdb_key(db, user.id)


@router.get("/movie/{tmdb_id}")
async def get_movie_awards(
    tmdb_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tvdb_key, tmdb_key = await _keys(db, current_user)
    try:
        awards = await awards_core.film_awards(tmdb_id, tvdb_key, tmdb_key)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch awards: {e}")
    return {"tmdb_id": tmdb_id, "awards": awards}


@router.get("/person/{person_id}")
async def get_person_awards(
    person_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tvdb_key, tmdb_key = await _keys(db, current_user)
    try:
        awards = await awards_core.person_awards(person_id, tvdb_key, tmdb_key)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch awards: {e}")
    return {"person_id": person_id, "awards": awards}
