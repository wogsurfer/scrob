"""Health of the download pipeline (qBittorrent, Sonarr, Radarr, Prowlarr,
Unpackerr), so a break shows on the dashboard instead of going unnoticed.

Each app's API key is read from its own config.xml every time, so a changed
key can't quietly break the checks. qBittorrent is covered through Sonarr's
and Radarr's own health checks (they report an unreachable download client).
In Docker the apps' folders are mounted read-only under /host (see
docker-compose.watchd.yaml); run directly on Windows, the real paths are used.
"""

import re
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx

IN_DOCKER = Path("/.dockerenv").exists()
HOST = "host.docker.internal" if IN_DOCKER else "127.0.0.1"
ARR_DIR = Path("/host/arr") if IN_DOCKER else Path(r"C:\ProgramData")
UNPACKERR_CONF = Path("/host/unpackerr/unpackerr.conf") if IN_DOCKER else Path(r"C:\ProgramData\unpackerr\unpackerr.conf")
UNPACKERR_LOG = Path("/host/unpackerr-logs/unpackerr.log") if IN_DOCKER else Path.home() / ".unpackerr" / "unpackerr.log"
DOWNLOADS = Path("/host/downloads") if IN_DOCKER else Path(r"D:\Downloads")

# (name, folder under ARR_DIR, default port, API version)
APPS = (("Sonarr", "Sonarr", 8989, "v3"), ("Radarr", "Radarr", 7878, "v3"), ("Prowlarr", "Prowlarr", 9696, "v1"))
# Unpackerr writes its queue to the log every minute; quieter than this, it's stopped.
UNPACKERR_QUIET = timedelta(minutes=10)
VIDEO = {".mkv", ".mp4", ".m4v", ".avi", ".m2ts", ".ts", ".wmv", ".mov"}
ARCHIVE = re.compile(r"\.(rar|r\d\d|zip|7z)$", re.I)
DISK_WARN, DISK_ERROR = 0.90, 0.95

OK, WARN, ERROR = "ok", "warn", "error"
_RANK = {OK: 0, WARN: 1, ERROR: 2}


def worst(statuses) -> str:
    return max(statuses, key=_RANK.__getitem__, default=OK)


def check(key: str, label: str, status: str, summary: str, details: list[str] | None = None) -> dict:
    return {"key": key, "label": label, "status": status, "summary": summary, "details": details or []}


def arr_config(folder: str) -> tuple[str | None, int | None]:
    """An app's API key and port from its config.xml."""
    try:
        xml = (ARR_DIR / folder / "config.xml").read_text(encoding="utf-8")
    except OSError:
        return None, None
    key = re.search(r"<ApiKey>([^<]+)</ApiKey>", xml)
    port = re.search(r"<Port>(\d+)</Port>", xml)
    return (key.group(1) if key else None), (int(port.group(1)) if port else None)


def unpackerr_keys(conf: str) -> dict[str, str]:
    """The API key Unpackerr holds for each app ({"sonarr": ..., "radarr": ...})."""
    keys = {}
    for app, body in re.findall(r"^\s*\[\[(\w+)\]\]\s*$(.*?)(?=^\s*\[|\Z)", conf, re.M | re.S):
        m = re.search(r'^\s*api_key\s*=\s*"([^"]*)"', body, re.M)
        if m:
            keys.setdefault(app.lower(), m.group(1))
    return keys


_LOG_LINE = re.compile(r"^\[(ERROR|WARN|INFO)\] (\d{4}/\d\d/\d\d \d\d:\d\d:\d\d) (.*)$")
_APP = r"(Sonarr|Radarr|Lidarr|Readarr|Whisparr)"


def explain(message: str) -> tuple[str | None, str, str]:
    """An Unpackerr error in plain English: (the app it's about, what it means,
    and its kind: "connection" for talking to an app, "unpack" for a download
    it couldn't unpack, else "other")."""
    m = re.match(_APP + r" \(", message)
    app = m.group(1) if m else None
    if app and re.search(r"invalid status code, 40[13]\b", message):
        return app, f"{app} is refusing Unpackerr: its API key for {app} is wrong. Update unpackerr.conf and restart Unpackerr.", "connection"
    if app and re.search(r"refused|No connection could be made|connection reset|no such host", message):
        return app, f"Unpackerr couldn't reach {app}: it wasn't running, or was restarting.", "connection"
    if app and re.search(r"deadline exceeded|Timeout|timed out", message, re.I):
        return app, f"{app} was too slow answering Unpackerr.", "connection"
    if app and re.search(r"invalid status code, 5\d\d", message):
        return app, f"{app} had an internal error answering Unpackerr.", "connection"
    m = re.match(r"Extraction Failed: ([^:]+): (.*)", message)
    if m:
        name, reason = m.group(1).strip(), m.group(2)
        if "checksum" in reason or "CRC" in reason:
            return None, f"Couldn't unpack {name}: one of its archive parts is damaged, so it needs downloading again.", "unpack"
        if "no space" in reason.lower():
            return None, f"Couldn't unpack {name}: the disk is full.", "unpack"
        return None, f"Couldn't unpack {name}: {reason[-120:]}", "unpack"
    return app, message, "other"


def in_the_past(app: str | None, text: str) -> str:
    """A fixed connection problem, said as what happened: "Radarr refused
    Unpackerr (its API key was wrong)"."""
    if "is refusing Unpackerr" in text:
        return f"{app} refused Unpackerr (its API key was wrong)"
    if "couldn't reach" in text:
        return f"Unpackerr couldn't reach {app}"
    if "too slow" in text:
        return f"{app} was slow answering Unpackerr"
    if "internal error" in text:
        return f"{app} had internal errors answering Unpackerr"
    return text


def log_problems(lines: list[str], since: datetime) -> list[dict]:
    """Unpackerr's errors since `since`, explained and grouped, most frequent
    first. A problem talking to an app counts as fixed once Unpackerr has since
    reached that app."""
    problems: dict[str, dict] = {}
    last_ok: dict[str, datetime] = {}
    for line in lines:
        m = _LOG_LINE.match(line.strip())
        if not m:
            continue
        try:
            when = datetime.strptime(m.group(2), "%Y/%m/%d %H:%M:%S")
        except ValueError:
            continue
        level, text = m.group(1), m.group(3)
        if level == "INFO":
            ok = re.match(r"\[" + _APP + r"\] Updated \(", text)
            if ok:
                last_ok[ok.group(1)] = when
            continue
        if when < since:
            continue
        app, plain, kind = explain(text)
        p = problems.setdefault(plain, {"text": plain, "app": app, "kind": kind, "count": 0, "first": when, "last": when})
        p["count"] += 1
        p["last"] = max(p["last"], when)
    for p in problems.values():
        p["fixed"] = p["kind"] == "connection" and p["app"] in last_ok and last_ok[p["app"]] > p["last"]
    return sorted(problems.values(), key=lambda p: (p["fixed"], -p["count"]))


def unpacked_leftovers(downloads: Path, older_than: timedelta, now: float | None = None) -> list[str]:
    """Download folders still holding archives but no video, untouched for a
    while: a release nothing unpacked."""
    now = now or time.time()
    found = []
    for category in (downloads.iterdir() if downloads.is_dir() else []):
        if not category.is_dir():
            continue
        for item in category.iterdir():
            if not item.is_dir():
                continue
            files = [f for f in item.rglob("*") if f.is_file()]
            if not files or now - max(f.stat().st_mtime for f in files) < older_than.total_seconds():
                continue
            if any(ARCHIVE.search(f.name) for f in files) and not any(f.suffix.lower() in VIDEO for f in files):
                found.append(f"{category.name}/{item.name}")
    return sorted(found)


async def _arr_checks(client: httpx.AsyncClient) -> tuple[list[dict], dict[str, str]]:
    """Each app's reachability, own health warnings and stuck queue items.
    Returns the checks and the apps' current keys."""
    out, keys = [], {}
    for name, folder, default_port, version in APPS:
        key, port = arr_config(folder)
        slug = name.lower()
        if not key:
            out.append(check(slug, name, WARN, "Couldn't read its settings file", [str(ARR_DIR / folder / "config.xml")]))
            continue
        keys[slug] = key
        base = f"http://{HOST}:{port or default_port}/api/{version}"
        headers = {"X-Api-Key": key}
        try:
            status = (await client.get(f"{base}/system/status", headers=headers)).raise_for_status().json()
            health = (await client.get(f"{base}/health", headers=headers)).raise_for_status().json()
        except Exception as exc:  # noqa: BLE001 - any failure means it isn't answering
            out.append(check(slug, name, ERROR, "Not answering", [f"{type(exc).__name__}: {exc}"[:200]]))
            continue
        problems = [h for h in health if h.get("type") in ("warning", "error")]
        details = [f"{h.get('type', '').title()}: {h.get('message', '')}" for h in problems]
        stuck = []
        if name != "Prowlarr":
            try:
                queue = (await client.get(f"{base}/queue", headers=headers, params={"pageSize": 100})).json()
                for r in queue.get("records", []):
                    if r.get("trackedDownloadStatus") in ("warning", "error") or r.get("trackedDownloadState") in ("importBlocked", "failedPending"):
                        msgs = "; ".join(m for s in r.get("statusMessages", []) for m in s.get("messages", []))
                        stuck.append(f"Stuck: {r.get('title', '?')}" + (f" ({msgs[:160]})" if msgs else ""))
            except Exception:  # noqa: BLE001
                pass
        level = ERROR if any(h.get("type") == "error" for h in problems) else WARN if problems or stuck else OK
        summary = (f"Version {status.get('version', '?')}" if level == OK
                   else f"{len(problems)} health warning{'s' * (len(problems) != 1)}" + (f", {len(stuck)} stuck" if stuck else ""))
        out.append(check(slug, name, level, summary, details + stuck))
    return out, keys


def _unpackerr_check(app_keys: dict[str, str]) -> dict:
    details, level = [], OK
    try:
        age = datetime.now() - datetime.fromtimestamp(UNPACKERR_LOG.stat().st_mtime)
    except OSError:
        return check("unpackerr", "Unpackerr", WARN, "Couldn't find its log", [str(UNPACKERR_LOG)])
    if age > UNPACKERR_QUIET:
        level = ERROR
        details.append(f"Its log hasn't changed for {int(age.total_seconds() // 60)} minutes: it looks stopped")
    try:
        conf = UNPACKERR_CONF.read_text(encoding="utf-8")
        for app, key in unpackerr_keys(conf).items():
            if app in app_keys and key != app_keys[app]:
                level = ERROR
                details.append(f"Its {app.title()} API key doesn't match {app.title()}'s: update unpackerr.conf and restart Unpackerr")
    except OSError:
        details.append("Couldn't read unpackerr.conf to check its keys")
    # The end of the log covers the last day comfortably.
    with UNPACKERR_LOG.open("rb") as f:
        f.seek(max(0, UNPACKERR_LOG.stat().st_size - 3_000_000))
        lines = f.read().decode("utf-8", "replace").splitlines()
    problems = log_problems(lines, datetime.now() - timedelta(hours=24))
    current = [p for p in problems if not p["fixed"]]
    fixed = [p for p in problems if p["fixed"]]
    times = lambda p: "once" if p["count"] == 1 else f"{p['count']} times"
    if current:
        level = worst([level, WARN])
        details += [f"{p['text']} ({times(p)}, last at {p['last']:%H:%M})" for p in current[:6]]
    if level == OK:
        summary = "Running, no errors in the last day"
        if fixed:
            summary = "Running; a problem earlier today has been fixed"
    else:
        summary = details[0] if len(details) == 1 else f"{len(details)} problems"
    # Fixed ones stay listed for the day, marked as such.
    details += [f"Fixed: {in_the_past(p['app'], p['text'])}, {times(p)} today until {p['last']:%H:%M}" for p in fixed[:3]]
    return check("unpackerr", "Unpackerr", level, summary, details)


def _downloads_check() -> list[dict]:
    out = []
    if not DOWNLOADS.is_dir():
        return [check("downloads", "Downloads folder", WARN, "Couldn't see the downloads folder", [str(DOWNLOADS)])]
    left = unpacked_leftovers(DOWNLOADS, timedelta(hours=6))
    out.append(check("downloads", "Downloads folder",
                     WARN if left else OK,
                     f"{len(left)} download{'s' * (len(left) != 1)} never unpacked" if left else "Nothing left packed",
                     left))
    usage = shutil.disk_usage(DOWNLOADS)
    used = usage.used / usage.total
    free_gb = usage.free / 2**30
    level = ERROR if used >= DISK_ERROR else WARN if used >= DISK_WARN else OK
    out.append(check("disk", "Disk space", level, f"{used:.0%} full, {free_gb:,.0f} GB free"))
    return out


_cache: dict = {"at": 0.0, "result": None}
CACHE_SECONDS = 120


async def pipeline_health(force: bool = False) -> dict:
    """Every check, worst first in importance order, cached briefly."""
    if not force and _cache["result"] and time.time() - _cache["at"] < CACHE_SECONDS:
        return _cache["result"]
    async with httpx.AsyncClient(timeout=8) as client:
        checks, keys = await _arr_checks(client)
    checks.append(_unpackerr_check(keys))
    checks += _downloads_check()
    result = {
        "status": worst(c["status"] for c in checks),
        "problems": sum(1 for c in checks if c["status"] != OK),
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "checks": checks,
    }
    _cache.update(at=time.time(), result=result)
    return result
