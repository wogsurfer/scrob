"""merge duplicate episode rows and keep one row per episode

Next Up could save the same episode twice when two requests overlapped, and
saved unaired episodes on every dashboard load, so some episodes have several
media rows with their plays spread between them. This merges each set into
one row, moving plays, ratings, collection entries (with their files), list
entries, playback state and translations onto it, then adds a unique index
on (show, season, episode) so it can't happen again.

The row kept is the one with the most plays, then the oldest. Blank details
on it (TMDB id, air time, artwork, synopsis) are filled from the others.

Revision ID: b8d2e3f4a5c6
Revises: a7c1d2e3f4b5
Create Date: 2026-10-25
"""

from alembic import op


revision = "b8d2e3f4a5c6"
down_revision = "a7c1d2e3f4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Each duplicate row and the row it merges into.
    op.execute("""
        CREATE TEMP TABLE episode_dupes ON COMMIT DROP AS
        WITH ranked AS (
            SELECT m.id, m.show_id, m.season_number, m.episode_number,
                   ROW_NUMBER() OVER (
                       PARTITION BY m.show_id, m.season_number, m.episode_number
                       ORDER BY (SELECT COUNT(*) FROM watch_events w WHERE w.media_id = m.id) DESC, m.id
                   ) AS rank
            FROM media m
            WHERE m.media_type = 'episode'
              AND m.show_id IS NOT NULL AND m.season_number IS NOT NULL AND m.episode_number IS NOT NULL
        )
        SELECT d.id AS dup_id, k.id AS keep_id
        FROM ranked d
        JOIN ranked k ON k.show_id = d.show_id AND k.season_number = d.season_number
                     AND k.episode_number = d.episode_number AND k.rank = 1
        WHERE d.rank > 1
    """)

    # Fill blanks on the kept row from its duplicates.
    op.execute("""
        UPDATE media k SET
            tmdb_id = COALESCE(k.tmdb_id, f.tmdb_id),
            first_aired_at = COALESCE(k.first_aired_at, f.first_aired_at),
            release_date = COALESCE(k.release_date, f.release_date),
            poster_path = COALESCE(k.poster_path, f.poster_path),
            overview = COALESCE(k.overview, f.overview),
            tmdb_data = COALESCE(k.tmdb_data, f.tmdb_data)
        FROM (
            SELECT DISTINCT ON (d.keep_id) d.keep_id, m.tmdb_id, m.first_aired_at, m.release_date,
                   m.poster_path, m.overview, m.tmdb_data
            FROM episode_dupes d JOIN media m ON m.id = d.dup_id
            ORDER BY d.keep_id, (m.tmdb_id IS NULL), m.id
        ) f
        WHERE k.id = f.keep_id
    """)

    # Plays and playback sessions have no per-media uniqueness: move them all.
    for table in ("watch_events", "playback_sessions"):
        op.execute(f"""
            UPDATE {table} t SET media_id = d.keep_id
            FROM episode_dupes d WHERE t.media_id = d.dup_id
        """)

    # Ratings: one per user. The kept row's own rating wins, else the first
    # duplicate's.
    op.execute("""
        DELETE FROM ratings r USING episode_dupes d
        WHERE r.media_id = d.dup_id AND (
            EXISTS (
                SELECT 1 FROM ratings k
                WHERE k.media_id = d.keep_id AND k.user_id = r.user_id
                  AND k.season_number IS NOT DISTINCT FROM r.season_number
                  AND k.episode_order IS NOT DISTINCT FROM r.episode_order
            )
            OR EXISTS (
                SELECT 1 FROM ratings o JOIN episode_dupes od ON o.media_id = od.dup_id
                WHERE od.keep_id = d.keep_id AND o.user_id = r.user_id
                  AND o.season_number IS NOT DISTINCT FROM r.season_number
                  AND o.episode_order IS NOT DISTINCT FROM r.episode_order
                  AND o.id < r.id
            )
        )
    """)
    op.execute("UPDATE ratings r SET media_id = d.keep_id FROM episode_dupes d WHERE r.media_id = d.dup_id")

    # Collection entries: one per user per episode. The kept row's entry wins,
    # else the user's first duplicate entry; the others' files move onto it
    # and the others go.
    op.execute("""
        CREATE TEMP TABLE collection_targets ON COMMIT DROP AS
        SELECT d.keep_id, c.user_id, COALESCE(
                   (SELECT k.id FROM collections k WHERE k.media_id = d.keep_id AND k.user_id = c.user_id),
                   MIN(c.id)
               ) AS target_id
        FROM collections c JOIN episode_dupes d ON c.media_id = d.dup_id
        GROUP BY d.keep_id, c.user_id
    """)
    op.execute("""
        UPDATE collection_files f SET collection_id = t.target_id
        FROM collections c
        JOIN episode_dupes d ON c.media_id = d.dup_id
        JOIN collection_targets t ON t.keep_id = d.keep_id AND t.user_id = c.user_id
        WHERE f.collection_id = c.id AND c.id <> t.target_id
    """)
    op.execute("""
        DELETE FROM collections c USING episode_dupes d, collection_targets t
        WHERE c.media_id = d.dup_id AND t.keep_id = d.keep_id AND t.user_id = c.user_id AND c.id <> t.target_id
    """)
    op.execute("UPDATE collections c SET media_id = d.keep_id FROM episode_dupes d WHERE c.media_id = d.dup_id")

    # The rest are unique per media: drop the duplicate's copy where the kept
    # row already has one, then move what's left. Duplicates of one episode
    # can clash with each other too, so only the first of them moves.
    for table, key in (
        ("list_items", "list_id"),
        ("playback_progress", "user_id"),
        ("media_translations", "language"),
    ):
        op.execute(f"""
            DELETE FROM {table} t USING episode_dupes d
            WHERE t.media_id = d.dup_id AND (
                EXISTS (SELECT 1 FROM {table} k WHERE k.media_id = d.keep_id AND k.{key} = t.{key})
                OR EXISTS (
                    SELECT 1 FROM {table} o JOIN episode_dupes od ON o.media_id = od.dup_id
                    WHERE od.keep_id = d.keep_id AND o.{key} = t.{key} AND o.id < t.id
                )
            )
        """)
        op.execute(f"UPDATE {table} t SET media_id = d.keep_id FROM episode_dupes d WHERE t.media_id = d.dup_id")

    op.execute("DELETE FROM media m USING episode_dupes d WHERE m.id = d.dup_id")

    op.execute("""
        CREATE UNIQUE INDEX uq_media_episode
        ON media (show_id, season_number, episode_number)
        WHERE media_type = 'episode'
          AND show_id IS NOT NULL AND season_number IS NOT NULL AND episode_number IS NOT NULL
    """)


def downgrade() -> None:
    # Merged rows can't be split again; only the guard is removed.
    op.execute("DROP INDEX IF EXISTS uq_media_episode")
