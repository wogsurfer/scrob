"""The Android app's updates: the newest build, published by android/publish.ps1
into data/app, for the app to check for and download over Tailscale."""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from core.config import settings
from dependencies import get_current_user
from models.users import User

router = APIRouter()


def _folder():
    return settings.data_dir / "app"


@router.get("/latest")
async def latest(current_user: User = Depends(get_current_user)):
    """The newest published build: its version code (higher is newer), name and size."""
    try:
        info = json.loads((_folder() / "version.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="No app build published yet")
    apk = _folder() / "watchd.apk"
    if not apk.exists():
        raise HTTPException(status_code=404, detail="No app build published yet")
    return {**info, "size": apk.stat().st_size}


@router.get("/download")
async def download(current_user: User = Depends(get_current_user)):
    apk = _folder() / "watchd.apk"
    if not apk.exists():
        raise HTTPException(status_code=404, detail="No app build published yet")
    return FileResponse(apk, media_type="application/vnd.android.package-archive", filename="watchd.apk")
