#!/bin/sh
# Nightly backup of everything Watchd keeps that isn't in git: the database,
# the stored files (cover scans, posters, backdrops, imports) and the .env
# settings. Runs in the "backup" service of docker-compose.watchd.yaml and
# writes to /out, which is BACKUP_DIR on the host (a cloud-synced folder).
#
# /out/database  one dump a day (pg_dump custom format), the last KEEP_DAYS kept
# /out/files     a copy of backend/data, without its caches (they rebuild)
# /out/config    the .env file
set -u

KEEP_DAYS="${KEEP_DAYS:-14}"
BACKUP_HOUR="${BACKUP_HOUR:-3}"

apk add --no-cache rsync >/dev/null 2>&1 || echo "backup: couldn't install rsync; files will be copied with cp"

backup() {
    stamp=$(date +%Y-%m-%d)
    mkdir -p /out/database /out/files /out/config
    echo "backup: starting $stamp"

    # Written under a temporary name so a half-written dump never looks complete.
    if pg_dump -Fc -f "/out/database/watchd-$stamp.dump.part"; then
        mv "/out/database/watchd-$stamp.dump.part" "/out/database/watchd-$stamp.dump"
    else
        rm -f "/out/database/watchd-$stamp.dump.part"
        echo "backup: database dump FAILED"
        return 1
    fi

    if command -v rsync >/dev/null 2>&1; then
        rsync -a --exclude 'cache/' --exclude 'image_cache/' /data/ /out/files/
    else
        cp -a /data/. /out/files/ && rm -rf /out/files/cache /out/files/image_cache
    fi
    cp /config/.env /out/config/env

    find /out/database -name 'watchd-*.dump' -mtime +"$KEEP_DAYS" -delete

    cat > /out/README.txt <<'TXT'
Watchd backup
=============

database/  A full copy of the database for each of the last 14 nights
           (watchd-YYYY-MM-DD.dump). The newest is the latest.
files/     The stored files: physical/covers (cover scans, posters,
           backdrops), imports and avatars.
config/    env: the settings file (.env), with the API keys and database
           password. Keep this folder private.

The code itself is on GitHub.

Restoring onto a fresh install
------------------------------
1. Clone the repository and copy config/env to .env in its folder.
2. Copy files/ into backend/data/.
3. Start the database only:
       docker compose -f docker-compose.watchd.yaml up -d db
4. Load the newest dump (replace the date):
       docker exec -i scrob-db-1 sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < database/watchd-YYYY-MM-DD.dump
5. Start everything:
       docker compose -f docker-compose.watchd.yaml up -d --build
TXT
    date '+%Y-%m-%d %H:%M' > /out/last-backup.txt
    echo "backup: done ($(du -sh /out/database/watchd-$stamp.dump | cut -f1) database)"
}

# One backup straight away, then every night at BACKUP_HOUR.
backup
while true; do
    now=$(date +%s)
    next=$(date -d "$(date +%Y-%m-%d) $(printf '%02d' "$BACKUP_HOUR"):00" +%s)
    [ "$next" -le "$now" ] && next=$((next + 86400))
    sleep $((next - now))
    backup
done
