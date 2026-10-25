#!/bin/sh
# Nightly backup of everything Watchd keeps that isn't in git: the database,
# the stored files (cover scans, posters, backdrops, imports) and the .env
# settings. Runs in the "backup" service of docker-compose.watchd.yaml and
# writes to /out, the project's backups folder (copied on to Google Drive).
#
# /out/database  one dump a day, the last KEEP_DAYS kept (encrypted)
# /out/files     a copy of backend/data, without its caches (they rebuild)
# /out/config    the .env file (encrypted)
#
# The database and .env hold API keys, tokens and password hashes, so they
# are encrypted with the key in /config/backup.key (backup.key in the
# project, kept out of git and out of the backups). Without that key they
# can't be restored, so keep a copy of it somewhere safe.
#
# Once a month, and on demand with
#     docker exec scrob-backup-1 sh /usr/local/bin/backup.sh test
# the newest dump is restored into a scratch database and its row counts
# checked against the live one; the result goes in /out/last-restore-test.txt.
set -u

KEEP_DAYS="${KEEP_DAYS:-14}"
BACKUP_HOUR="${BACKUP_HOUR:-3}"
KEY=/config/backup.key
# The tables a restore test compares.
TEST_TABLES="users media shows watch_events ratings lists list_items physical_items physical_pick_values user_settings"

encrypt() { openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass "file:$KEY" "$@"; }
decrypt() { openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass "file:$KEY" "$@"; }

# Backups from before encryption: encrypt them, and remove the plain copies.
encrypt_old() {
    for f in /out/*.dump /out/database/*.dump; do
        [ -f "$f" ] || continue
        if encrypt -in "$f" -out "$f.enc.part"; then
            mv "$f.enc.part" "$f.enc" && rm -f "$f"
            echo "backup: encrypted $(basename "$f")"
        fi
    done
    if [ -f /out/config/env ]; then
        encrypt -in /out/config/env -out /out/config/env.enc && rm -f /out/config/env
    fi
}

backup() {
    stamp=$(date +%Y-%m-%d)
    mkdir -p /out/database /out/files /out/config
    echo "backup: starting $stamp"
    if [ ! -s "$KEY" ]; then
        # Never write the secrets out unencrypted.
        echo "backup: no key at $KEY, so nothing was backed up"
        return 1
    fi
    encrypt_old

    # Written under a temporary name so a half-written dump never looks complete.
    set -o pipefail
    if pg_dump -Fc | encrypt -out "/out/database/watchd-$stamp.dump.enc.part"; then
        mv "/out/database/watchd-$stamp.dump.enc.part" "/out/database/watchd-$stamp.dump.enc"
    else
        rm -f "/out/database/watchd-$stamp.dump.enc.part"
        echo "backup: database dump FAILED"
        set +o pipefail
        return 1
    fi
    set +o pipefail

    rsync -a --exclude 'cache/' --exclude 'image_cache/' /data/ /out/files/
    encrypt -in /config/.env -out /out/config/env.enc

    find /out/database -name 'watchd-*.dump.enc' -mtime +"$KEEP_DAYS" -delete

    cat > /out/README.txt <<'TXT'
Watchd backup
=============

database/  A full copy of the database for each of the last 14 nights
           (watchd-YYYY-MM-DD.dump.enc). The newest is the latest.
files/     The stored files: physical/covers (cover scans, posters,
           backdrops), imports and avatars.
config/    env.enc: the settings file (.env).

The database and settings are encrypted, because they hold API keys,
tokens and password hashes. Restoring them needs backup.key, the key
file kept in the Watchd folder on the PC (not in these backups). Keep a
copy of that key somewhere safe, away from this backup.

The code itself is on GitHub.

Restoring onto a fresh install
------------------------------
1. Clone the repository and put backup.key in its folder.
2. Copy files/ into backend/data/.
3. Decrypt the settings and the newest dump (replace the date). From the
   repository folder, with this backup folder at BACKUP:
       docker run --rm -v "%cd%:/k" -v "BACKUP:/b" alpine sh -c "apk add -q openssl && openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass file:/k/backup.key -in /b/config/env.enc -out /k/.env && openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass file:/k/backup.key -in /b/database/watchd-YYYY-MM-DD.dump.enc -out /k/restore.dump"
4. Start the database only:
       docker compose -f docker-compose.watchd.yaml up -d db
5. Load the dump:
       docker exec -i scrob-db-1 sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < restore.dump
6. Start everything, then delete restore.dump:
       docker compose -f docker-compose.watchd.yaml up -d --build
TXT
    date '+%Y-%m-%d %H:%M' > /out/last-backup.txt
    echo "backup: done ($(du -sh "/out/database/watchd-$stamp.dump.enc" | cut -f1) database)"
}

# Restore the newest dump into a scratch database and compare it with the
# live one.
restore_test() {
    newest=$(ls -1 /out/database/watchd-*.dump.enc 2>/dev/null | sort | tail -n 1)
    out=/out/last-restore-test.txt
    if [ -z "$newest" ]; then
        echo "FAILED $(date '+%Y-%m-%d %H:%M'): no backup to test" | tee "$out"
        return 1
    fi
    scratch=watchd_restore_test
    tmp=/tmp/restore-test.dump
    dropdb --if-exists "$scratch" && createdb "$scratch" || { echo "FAILED: couldn't make the scratch database" | tee "$out"; return 1; }
    if ! decrypt -in "$newest" -out "$tmp"; then
        echo "FAILED $(date '+%Y-%m-%d %H:%M'): $(basename "$newest") wouldn't decrypt" | tee "$out"
        dropdb --if-exists "$scratch"; return 1
    fi
    pg_restore -d "$scratch" --no-owner "$tmp" 2>/tmp/restore-test.log
    rm -f "$tmp"
    result=PASSED
    report=""
    for t in $TEST_TABLES; do
        live=$(psql -At -c "SELECT count(*) FROM $t" 2>/dev/null)
        restored=$(psql -At -d "$scratch" -c "SELECT count(*) FROM $t" 2>/dev/null)
        # The live database may have moved on since the backup, so a table
        # fails only when the restore is missing more than a tenth of it.
        if [ -z "$restored" ] || [ $((restored * 10)) -lt $((${live:-0} * 9)) ]; then result=FAILED; fi
        report="$report
  $t: live ${live:-?}, restored ${restored:-?}"
    done
    dropdb --if-exists "$scratch"
    {
        echo "$result $(date '+%Y-%m-%d %H:%M'): restored $(basename "$newest")$report"
        echo "(Counts can differ by what's changed since the backup was made.)"
    } | tee "$out"
    [ "$result" = PASSED ]
}

if [ "${1:-}" = test ]; then
    restore_test
    exit $?
fi

# One backup straight away, then every night at BACKUP_HOUR; a restore test
# on the first of each month.
backup
while true; do
    now=$(date +%s)
    next=$(date -d "$(date +%Y-%m-%d) $(printf '%02d' "$BACKUP_HOUR"):00" +%s)
    [ "$next" -le "$now" ] && next=$((next + 86400))
    sleep $((next - now))
    backup && [ "$(date +%d)" = 01 ] && restore_test
done
