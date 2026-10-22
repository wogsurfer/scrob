from services.emby.client import EmbyClient
from sqlalchemy import select
from models.emby_library_stats import EmbyLibraryStats
from models.show import Show


class EmbySync:

    def __init__(self, db):
        self.db = db
        self.client = EmbyClient()

    async def sync_shows(self, items):
        for item in items:
            provider_ids = item.get("ProviderIds", {})
            emby_id = item["Id"]

            tmdb_id = provider_ids.get("Tmdb")
            tvdb_id = provider_ids.get("Tvdb") or provider_ids.get("TVDB")

            with self.db.no_autoflush:
                existing = await self.db.scalar(
                    select(Show).where(Show.emby_id == emby_id)
                )

            if existing is None and tmdb_id:
                with self.db.no_autoflush:
                    existing = await self.db.scalar(
                        select(Show).where(Show.tmdb_id == int(tmdb_id))
                    )

            if existing:
                existing.emby_id = emby_id

                if tmdb_id and existing.tmdb_id is None:
                    existing.tmdb_id = int(tmdb_id)

                if tvdb_id and existing.tvdb_id is None:
                    existing.tvdb_id = int(tvdb_id)

                if not existing.title:
                    existing.title = item["Name"]

            else:
                show = Show(
                    emby_id=emby_id,
                    tmdb_id=int(tmdb_id) if tmdb_id else None,
                    tvdb_id=int(tvdb_id) if tvdb_id else None,
                    title=item["Name"],
                )
                self.db.add(show)

    async def sync(self):
        movies = await self.client.get(
            "/Users/99bbc6be59ab459a85702599516b234e/Items",
            IncludeItemTypes="Movie",
            Recursive="true",
        )

        shows = await self.client.get(
            "/Users/99bbc6be59ab459a85702599516b234e/Items",
            IncludeItemTypes="Series",
            Recursive="true",
            Fields="ProviderIds,Overview,Genres,ProductionYear,Status,DateCreated",
        )

        await self.sync_shows(shows["Items"])

        episodes = await self.client.get(
            "/Users/99bbc6be59ab459a85702599516b234e/Items",
            IncludeItemTypes="Episode",
            Recursive="true",
        )

        stats = await self.db.scalar(select(EmbyLibraryStats))

        if stats is None:
            stats = EmbyLibraryStats()
            self.db.add(stats)

        stats.movies = len(movies["Items"])
        stats.shows = len(shows["Items"])
        stats.episodes = len(episodes["Items"])

        await self.db.commit()

        return {
            "movies": stats.movies,
            "shows": stats.shows,
            "episodes": stats.episodes,
        }
