<div align="center">
  <img src="frontend/src/assets/watchd-icon-red.png" alt="Watchd" width="110" />
  <h1>Watchd</h1>
  <p>A self-hosted film and TV tracker, with a physical disc collection and an Android app.</p>
</div>

---

Watchd keeps track of everything you watch: films, shows, seasons and episodes, with your ratings, lists, history and stats. It syncs with **Emby**, **Jellyfin** and **Plex**, scrobbles as you play, and catalogues the Blu-rays and DVDs on your shelf.

It started life as a fork of **[Scrob](https://github.com/ellite/scrob)** by [Henrique](https://henrique.pt), and keeps everything Scrob does. Go and give the original a star.

## Contents

- [What Watchd adds](#what-watchd-adds)
- [Screenshots](#screenshots)
- [Getting Started](#getting-started)
- [The Android app](#the-android-app)
- [Configuration](#configuration)
- [Webhooks](#webhooks-real-time-scrobbling)
- [OIDC / Single Sign-On](#oidc--single-sign-on)
- [Development](#development)
- [Credits and licence](#credits-and-licence)

## What Watchd adds

- **A redesigned site**: a new dashboard, poster cards everywhere with IMDb scores, Trakt-style action buttons, and half-star ratings.
- **Next Up and the calendar**: a Next Up row for every show you're watching, a Next Episode and Recently Aired strip on show pages, and a week grid of what's airing.
- **Shows, seasons and episodes**: season posters, progress bars, series finales, guest and regular cast counts that add up, and per-episode IMDb ratings.
- **People and awards**: full filmographies, plus award nominations and wins for films and people from open award datasets.
- **Songs and source material**: songs from films and shows (no score or dialogue), and the book or work a film was adapted from.
- **Physical disc collection**: catalogue your Blu-rays, 4K discs and DVDs by barcode, with box sets, editions, format and region logos, and a shelf that files films the way they sit on yours.
- **Stats**: yearly and all-time stats, with weekly charts, genres, streaks and totals.
- **Holiday themes**: the site and app dress up for Christmas, Halloween, Star Wars Day, Oscars night and more.
- **An Android app**: native, built with Kotlin and Jetpack Compose, with a home-screen widget, new-episode notifications, Share into Watchd, and self-updates.
- **Backups**: nightly encrypted backups that test themselves.

Watchd was built for one home setup, so a few extras only switch on if you have the same things: the download pipeline panel (Sonarr, Radarr, Prowlarr, Unpackerr and Bazarr) and Emby season posters.

## Screenshots

<img src="docs/screenshots/watchd/01-watchd.jpg" alt="Watchd" width="49%" />
<img src="docs/screenshots/watchd/02-next-up.jpg" alt="Next Up" width="49%" />
<img src="docs/screenshots/watchd/03-shows.jpg" alt="Shows" width="49%" />
<img src="docs/screenshots/watchd/04-cast-and-crew.jpg" alt="Cast and crew" width="49%" />
<img src="docs/screenshots/watchd/05-episodes-and-films.jpg" alt="Episodes and films" width="49%" />
<img src="docs/screenshots/watchd/06-disc-collection.jpg" alt="Disc collection" width="49%" />
<img src="docs/screenshots/watchd/07-stats.jpg" alt="Stats" width="49%" />
<img src="docs/screenshots/watchd/08-holiday-themes.jpg" alt="Holiday themes" width="49%" />
<img src="docs/screenshots/watchd/09-android-app.jpg" alt="Android app" width="49%" />

## Getting Started

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with Docker Compose
- [Git](https://git-scm.com/downloads)
- A free [TMDB Read Access Token](https://www.themoviedb.org/settings/api), for metadata, search and images

### Install

Watchd is built from source; there's no published image.

1. Get the code:

```bash
git clone https://github.com/wogsurfer/watchd.git
cd watchd
```

2. Open `docker-compose.yaml` and change the values marked `changeme`: the database password (in both places it appears) and `SECRET_KEY`. Generate a key with `openssl rand -hex 32`. Set `TZ` to your timezone, for example `Europe/London`.

3. Build and start it:

```bash
docker compose up -d --build
```

The first build takes a few minutes.

### First setup

1. Open `http://localhost:7330` and create your account. The first account is the admin.
2. Go to **Settings → Integrations**, add your TMDB Read Access Token, and connect Emby, Jellyfin or Plex.
3. Choose which libraries to sync, then run your first sync.

Every install is separate: each one has its own database, accounts and watch history. To let family or friends use yours, set `ENABLE_REGISTRATIONS: "true"` and they can make their own accounts.

### Updating

```bash
git pull
docker compose up -d --build
```

Database migrations run on their own at startup.

## The Android app

The app lives in `android/`. Build it with Android Studio, or from the command line:

```bash
cd android
./gradlew assembleDebug
```

Install the APK from `android/app/build/outputs/apk/debug/`, then sign in with your server's address (for example `http://192.168.1.20:7330`) and your Watchd username and password. Releases with a ready-made APK are on the [Releases page](https://github.com/wogsurfer/watchd/releases) when available.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | - | **Required.** JWT signing key. Generate with `openssl rand -hex 32`. |
| `DATABASE_URL` | - | **Required** (standard image). PostgreSQL connection string (`postgresql+asyncpg://...`). Optional on the omnibus image — if omitted, the embedded database is used. |
| `ENABLE_REGISTRATIONS` | `false` | Allow new users to register. The first user can always register regardless of this setting. |
| `REGISTRATION_MAX_ALLOWED_USERS` | `0` | Maximum number of registered users. `0` = unlimited. |
| `TZ` | `UTC` | Container timezone (e.g. `Europe/Lisbon`). |
| `PUID` | `1000` | User ID to run the process as. |
| `PGID` | `1000` | Group ID to run the process as. |
| `BACKEND_PORT` | `7331` | Internal port the backend binds to. Override only if `7331` conflicts on bare metal. |
| `OIDC_ENABLED` | `false` | Enable OIDC login. |
| `OIDC_DISABLE_PASSWORD_LOGIN` | `false` | Enforce OIDC-only login (disables username/password). |

See `docker-compose.yaml` for the full list of OIDC variables and other variables.

### Reverse proxy

Watchd listens on port `7330`. Place a reverse proxy (Caddy, Nginx, Traefik) in front for HTTPS - required for the PWA install prompt on non-localhost addresses.

```
# Caddyfile
watchd.yourdomain.com {
    reverse_proxy localhost:7330
}
```

### External PostgreSQL

Remove the `scrob-db` service and set `DATABASE_URL` to your existing instance:

```yaml
DATABASE_URL: postgresql+asyncpg://user:password@your-db-host:5432/scrob
```

## Nuvio Cloud Synchronization

Watchd connects to the [Nuvio public Cloud API](https://nuvio.tv/docs) at `https://api.nuvio.tv`. A TMDB Read Access Token must be configured in Watchd so Nuvio content identifiers can be matched to movies and shows.

### Connect Nuvio

1. Open **Settings → Media & Cloud Connections** and select **Add Connection**.
2. Choose **Nuvio**, then enter a connection name, your Nuvio email, and your Nuvio password.
3. Select **Test** to authenticate and load the profiles attached to the account.
4. Select the Nuvio profile to synchronize, choose the pull and push options, then select **Add**.

Watchd exchanges the email and password for a refresh token. The password is never persisted. Refresh-token rotation is handled automatically during connection checks and synchronization.

Each connection targets one Nuvio profile. Add another connection if you need to synchronize another profile from the same account.

### Synchronization Directions

| Direction | Setting | Behavior |
|---|---|---|
| Nuvio → Watchd | **Collection status** | Imports the profile's library movies and series. |
| Nuvio → Watchd | **Watched status** | Imports watched movies and episodes with their latest watch timestamps. |
| Nuvio → Watchd | **Playback progress** | Imports position and duration into Continue Watching. |
| Watchd → Nuvio | **Watched status** | Pushes watched and unwatched changes made in Watchd or imported from another connected provider. |
| Watchd → Nuvio | **Playback progress** | Pushes current playback positions into Nuvio's Continue Watching state as non-destructive upserts. |

**Sync now** runs an inbound synchronization using the enabled Nuvio → Watchd settings. **Push** sends the enabled watched-history and playback-progress data from Watchd to Nuvio. Both operations use non-destructive upserts; items absent from Watchd are not removed from Nuvio.

Library membership is currently pull-only. Ratings are not synchronized with Nuvio.

### Scheduling and Limitations

**Auto Pull** repeats the enabled inbound synchronization every 15 minutes, 30 minutes, 1 hour, 3 hours, 6 hours, 12 hours, 24 hours, or 48 hours. Nuvio synchronization is polling-based; Nuvio does not use the media-server webhook URLs documented below.

Inbound Nuvio identifiers are normalized to TMDB for Watchd's internal matching. Before an outbound push, Watchd resolves those TMDB identifiers to Nuvio-compatible bare IMDb identifiers (`tt...`) and caches the mapping. Unsupported identifiers are skipped rather than attached to the wrong title.

## MDBList Synchronization

1. Open **Settings → Connections → MDBList**.
2. Copy the API key from [MDBList Preferences](https://mdblist.com/preferences), paste it into Watchd, and select **Save Changes**.
3. Choose the data to import under **MDBList → Watchd**, then select **Pull**. MDBList pulls run only when this button is selected.
4. To send changes back, enable the required **Watchd → MDBList** options. Watched-state and rating edits are pushed as they happen; edits to the managed **MDBList - Watchlist** are pushed to the MDBList watchlist.

The manual **Push** action sends the complete enabled watched, ratings, or managed-watchlist snapshot. MDBList pagination follows `next_cursor` and requests the documented maximum of 1,000 items per page.

## Webhooks (Real-time Scrobbling)

Webhooks update your watch history and Continue Watching in real time. Each user's webhook URL is shown in **Settings** next to the relevant integration.

```
# Jellyfin, Plex, Emby - connection_id is shown in Settings next to each server
https://your-watchd-url/api/proxy/webhooks/{jellyfin|plex|emby}/{connection_id}?api_key=YOUR_API_KEY

# Kodi - no connection, just the API key
https://your-watchd-url/api/proxy/webhooks/kodi?api_key=YOUR_API_KEY
```

### Jellyfin

1. In Jellyfin, go to **Dashboard → Plugins → Catalogue**, install **Webhook**, then restart.
2. Go to **Dashboard → Plugins → Webhook → Add Generic Destination**.
3. Paste your Watchd Jellyfin webhook URL.
4. Enable notification types: `Playback Start`, `Playback Progress`, `Playback Stop`, `User Data Saved` (this is what fires when you manually mark something watched/unwatched - the plugin has no separate "Mark Played" event).
5. Enable item types: `Movies` and `Episodes`.
6. **Leave the Template field blank** and check **"Send all properties (ignore templates)"**.

> Do not use a custom template - Jellyfin's template engine produces invalid JSON. "Send all properties" sends a well-formed payload that Watchd parses correctly.

### Plex

Plex webhooks require a **Plex Pass** subscription.

1. Go to [plex.tv/account](https://www.plex.tv/account/) → **Webhooks → Add Webhook**.
2. Paste your Watchd Plex webhook URL.
3. In Watchd → Settings, enter your **Plex username** so events are attributed to the right account.

### Emby

1. In Emby, go to **Dashboard → Notifications → Add Notification → Webhook**.
2. Paste your Watchd Emby webhook URL.
3. Enable events: `Playback Start`, `Playback Progress`, `Playback Stop`.

### Kodi

Kodi scrobbling uses the **[scrob-kodi](https://github.com/ellite/scrob-kodi)** add-on - no manual webhook configuration needed.

1. Install the **scrob-kodi** add-on from the [scrob-kodi repository](https://github.com/ellite/scrob-kodi).
2. In the add-on settings, enter your Watchd URL and your API key (found in **Settings → Account**).
3. The add-on will automatically send playback events to Watchd as you watch.

## OIDC / Single Sign-On

Watchd supports any OpenID Connect provider (Authelia, Authentik, Keycloak, Google, etc.).

```yaml
OIDC_ENABLED: "true"
OIDC_PROVIDER_NAME: "Authelia"
OIDC_CLIENT_ID: "scrob"
OIDC_CLIENT_SECRET: "your-secret"
OIDC_AUTH_URL: "https://auth.yourdomain.com/api/oidc/authorization"
OIDC_TOKEN_URL: "https://auth.yourdomain.com/api/oidc/token"
OIDC_USERINFO_URL: "https://auth.yourdomain.com/api/oidc/userinfo"
OIDC_REDIRECT_URL: "https://watchd.yourdomain.com/oidc-callback"
OIDC_AUTO_CREATE_USERS: "true"
# OIDC_DISABLE_PASSWORD_LOGIN: "true"  # uncomment to enforce SSO-only
```

Register Watchd as a client in your provider with redirect URI: `https://watchd.yourdomain.com/oidc-callback`

## Email Validation & SMTP

Watchd can require new users to verify their email address before logging in. Providing SMTP settings also enables the **forgot password** link on the login page.

```yaml
REQUIRE_EMAIL_VALIDATION: "true"
SERVER_URL: "https://watchd.yourdomain.com"
SMTP_ADDRESS: "smtp.gmail.com"
SMTP_PORT: "587"
SMTP_ENCRYPTION: "tls"
SMTP_USERNAME: "myemail@gmail.com"
SMTP_PASSWORD: "your-app-password"
FROM_EMAIL: "myemail@gmail.com"
```

| Variable | Default | Description |
|---|---|---|
| `REQUIRE_EMAIL_VALIDATION` | `false` | Require new users to verify their email before logging in. |
| `SERVER_URL` | - | Public URL of your Watchd instance, used to build the validation link in emails. |
| `SMTP_ADDRESS` | - | SMTP server hostname. |
| `SMTP_PORT` | `587` | SMTP server port. |
| `SMTP_ENCRYPTION` | `tls` | Encryption method - `tls` or `ssl`. |
| `SMTP_USERNAME` | - | SMTP login username. |
| `SMTP_PASSWORD` | - | SMTP login password (use an app password if using Gmail). |
| `FROM_EMAIL` | - | Address emails are sent from. |

## Development

<details>
<summary>View instructions</summary>

### Requirements

- Python 3.12+, [uv](https://docs.astral.sh/uv/)
- Node.js 22+
- PostgreSQL 16 (via Docker is easiest)

### Setup

```bash
git clone https://github.com/wogsurfer/watchd.git
cd watchd

# Start a local database
docker compose -f docker-compose-test-db.yaml up -d

# Copy and fill in the environment file
cp .env.example .env
# Edit .env - set POSTGRES_* and SECRET_KEY at minimum
```

### Backend

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn main:app --reload --port 7331
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend dev server starts on `http://localhost:4321` and proxies API calls to the backend on `7331`.

</details>

## Credits and licence

Watchd is built on [Scrob](https://github.com/ellite/scrob) by [Henrique](https://henrique.pt) and its [contributors](https://github.com/ellite/scrob/graphs/contributors). The Kodi add-on, Nuvio and MDBList sync, OIDC and much of the core come from there.

Metadata comes from [TMDB](https://www.themoviedb.org), [TheTVDB](https://thetvdb.com), [TVmaze](https://www.tvmaze.com) and [Wikidata](https://www.wikidata.org). Watchd isn't endorsed by any of them.

Like Scrob, Watchd is licensed under the [GNU General Public License v3.0](LICENSE.md): you're free to use, change and share it, as long as anything built from it is also released under the GPLv3.
