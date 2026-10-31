"""watchlist: a film leaves it once watched

A trigger on watch_events takes a film off the watcher's watchlist as soon as
a watch of it is recorded, however it arrives (webhook, manual, check-in,
sync, import), as Trakt's watchlist did. Films already watched but still
listed are taken off too.

Revision ID: e4d8e9f0a1b2
Revises: d3c7d8e9f0a1
Create Date: 2026-10-31
"""

from alembic import op


revision = "e4d8e9f0a1b2"
down_revision = "d3c7d8e9f0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION watchlist_drop_watched() RETURNS trigger AS $$
        BEGIN
            DELETE FROM movie_watchlist w
            USING media m
            WHERE m.id = NEW.media_id
              AND m.media_type = 'movie'
              AND w.user_id = NEW.user_id
              AND w.tmdb_id = m.tmdb_id;
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql
    """)
    # Only a finished watch counts, not one still in progress.
    op.execute("""
        CREATE TRIGGER watch_events_drop_from_watchlist
        AFTER INSERT OR UPDATE OF watched_at ON watch_events
        FOR EACH ROW WHEN (NEW.watched_at IS NOT NULL)
        EXECUTE FUNCTION watchlist_drop_watched()
    """)
    op.execute("""
        DELETE FROM movie_watchlist w
        USING media m, watch_events e
        WHERE m.tmdb_id = w.tmdb_id
          AND m.media_type = 'movie'
          AND e.media_id = m.id
          AND e.user_id = w.user_id
          AND e.watched_at IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS watch_events_drop_from_watchlist ON watch_events")
    op.execute("DROP FUNCTION IF EXISTS watchlist_drop_watched()")
