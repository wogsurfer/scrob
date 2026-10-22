import httpx

from core.config import settings


class EmbyClient:
    def __init__(self):
        if not settings.emby_server:
            raise RuntimeError("Emby server not configured")

        self.server = settings.emby_server.rstrip("/")
        self.api_key = settings.emby_api_key

    async def get(self, path: str, **params):
        params["api_key"] = self.api_key

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.server}{path}",
                params=params,
            )
            response.raise_for_status()
            return response.json()