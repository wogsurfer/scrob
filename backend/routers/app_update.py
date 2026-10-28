"""The Android app's updates: the newest build, published by android/publish.ps1
into data/app, for the app to check for and download over Tailscale."""
import json
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from jose import JWTError, jwt

from core.config import settings
from core.security import ALGORITHM, create_access_token
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


@router.get("/link")
async def download_link(current_user: User = Depends(get_current_user)):
    """A link to the newest build that works for 15 minutes without signing
    in, for the phone's browser to download: the app opens it there, so the
    app needn't install apps itself (which Play Protect treats as harmful)."""
    token = create_access_token("app-download", expires_delta=timedelta(minutes=15), extra_claims={"type": "app_download"})
    return {"url": f"/api/proxy/app/file/{token}/watchd.apk"}


@router.get("/file/{token}/watchd.apk")
async def download_file(token: str):
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=403, detail="This download link has expired")
    if payload.get("type") != "app_download":
        raise HTTPException(status_code=403, detail="Not a download link")
    apk = _folder() / "watchd.apk"
    if not apk.exists():
        raise HTTPException(status_code=404, detail="No app build published yet")
    return FileResponse(apk, media_type="application/vnd.android.package-archive", filename="watchd.apk")
