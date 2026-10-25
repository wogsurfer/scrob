# The nightly backup: Postgres's own tools, plus rsync for the files and
# openssl to encrypt what holds secrets.
FROM postgres:16-alpine
RUN apk add --no-cache rsync openssl
COPY backup.sh /usr/local/bin/backup.sh
ENTRYPOINT ["/bin/sh", "/usr/local/bin/backup.sh"]
