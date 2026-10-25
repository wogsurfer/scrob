const BACKEND_PORT = "8000";
const BASE = `http://127.0.0.1:${BACKEND_PORT}`;

type ParamValue = string | number | boolean | undefined;

async function request<T>(
  path: string,
  method: string = "GET",
  params?: Record<string, ParamValue | ParamValue[]>,
  body?: unknown,
  token?: string
): Promise<T> {
  const url = new URL(
    path.startsWith("/") ? path.slice(1) : path,
    BASE.endsWith("/") ? BASE : BASE + "/"
  );

  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v === undefined) return;

      if (Array.isArray(v)) {
        v.forEach(item => {
          if (item !== undefined)
            url.searchParams.append(k, String(item));
        });
      } else {
        url.searchParams.set(k, String(v));
      }
    });
  }

  const headers: Record<string, string> = {};

  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  let finalBody: BodyInit | undefined;

  if (body instanceof FormData) {
    finalBody = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    finalBody = JSON.stringify(body);
  }

  const res = await fetch(url.toString(), {
    method,
    headers,
    body: finalBody,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text);
  }

  return await res.json();
}

async function get<T>(path: string, params?: Record<string, ParamValue | ParamValue[]>, token?: string): Promise<T> {
  return request<T>(path, "GET", params, undefined, token);
}

async function post<T>(path: string, body?: unknown, token?: string): Promise<T> {
  return request<T>(path, "POST", undefined, body, token);
}

async function put<T>(path: string, body?: unknown, token?: string): Promise<T> {
  return request<T>(path, "PUT", undefined, body, token);
}

async function patch<T>(path: string, body?: unknown, token?: string): Promise<T> {
  return request<T>(path, "PATCH", undefined, body, token);
}

async function del<T>(path: string, token?: string): Promise<T> {
  return request<T>(path, "DELETE", undefined, undefined, token);
}

// Shared sub-types

export interface CastMember {
  tmdb_id: number;
  name: string;
  character: string;
  profile_path: string | null;
}

export interface CrewCredit {
  tmdb_id: number;
  name: string;
  job: string;
  department?: string | null;
  profile_path?: string | null;
  episode_count?: number | null;
}

export interface Network {
  id: number;
  name: string;
  logo_path: string | null;
}

export interface ProductionCompany {
  id: number;
  name: string;
  logo_path: string | null;
}

export interface SeasonMeta {
  season_number: number;
  name: string;
  overview: string | null;
  poster_path: string | null;
  episode_count: number;
  air_date: string | null;
  tmdb_season_id?: number | null;
  tmdb_rating?: number | null;
}

export interface SeasonState {
  watched: boolean;
  in_library: boolean;
  collection_pct: number;
  watch_pct: number;
  user_rating: number | null;
  episode_count?: number;
  watched_count?: number;
  has_aired?: boolean;
}

export interface EpisodeItem {
  badge?: string | null;
  id: number | null;
  tmdb_id: number;
  episode_number: number;
  title: string;
  overview: string | null;
  air_date: string | null;
  poster_path: string | null;
  tmdb_rating: number;
  runtime: number | null;
  in_library: boolean;
  watched: boolean;
  user_rating: number | null;
  in_lists: number[];
}

export interface ShowSummary {
  tmdb_id: number;
  title: string;
  poster_path: string | null;
  backdrop_path: string | null;
  seasons_meta: SeasonMeta[];
  networks: Network[];
}

export interface Season {
  show: ShowSummary;
  name: string;
  overview: string | null;
  poster_path: string | null;
  backdrop_path: string | null;
  air_date: string | null;
  tmdb_rating?: number | null;
  imdb_rating?: number | null;
  episodes: EpisodeItem[];
  season_number: number;
  show_watched: boolean;
  season_watched: boolean;
  season_watch_pct: number;
  season_in_library: boolean;
  season_collection_pct: number;
  season_user_rating: number | null;
  show_in_lists: number[];
  show_in_library: boolean;
  show_collection_pct: number;
  show_request_enabled: boolean;
  show_is_monitored: boolean;
}

export interface EpisodeDetail {
  show: ShowSummary;
  badge?: string | null;
  title: string;
  overview: string | null;
  still_path: string | null;
  air_date: string | null;
  episode_number: number;
  season_number: number;
  runtime: number | null;
  tmdb_rating: number | null;
  tmdb_id: number;
  id: number | null;
  in_library: boolean;
  watched: boolean;
  in_lists: number[];
  collection_pct: number;
  user_rating?: number | null;
  play_count?: number;
  cast: CastMember[];
  guest_stars: CastMember[];
  crew?: CrewCredit[];
  episodes: EpisodeItem[];
  library: {
    resolution: string;
    video_codec: string;
    audio_codec: string;
    audio_channels: string;
    audio_languages: string[];
    subtitle_languages: string[];
  } | null;
}

export interface PersonCredit {
  tmdb_id: number;
  type: "movie" | "series";
  title: string;
  poster_path: string | null;
  release_date: string | null;
  character: string | null;
  department?: string | null;
  job?: string | null;
  watched?: boolean;
  in_lists?: number[];
  in_library?: boolean;
  collection_pct?: number;
}

export interface PersonDetail {
  tmdb_id: number;
  name: string;
  profile_path: string | null;
  known_for_department: string | null;
  biography: string | null;
  birthday: string | null;
  place_of_birth: string | null;
  credits: PersonCredit[];
  total_credits: number;
  all_credits: number;
  watched_all_credits: number;
  credit_counts: Record<string, number>;
  watched_credit_counts: Record<string, number>;
  selected_category: string;
  imdb_highest: {
    rating: number;
    title: string;
  } | null;
  imdb_lowest: {
    rating: number;
    title: string;
  } | null;
  page: number;
  page_size: number;
  in_lists: number[];
}

export interface WatchEvent {
  id: number;
  media: MediaItem;
  user_id: number;
  watched_at: string | null;
  watch_source: string | null;
  completed: boolean;
  progress_percent: number | null;
}

export interface SyncJob {
  id: number;
  source: string;
  status: string;
  total_items: number;
  processed_items: number;
  error_message: string | null;
  updated_at: string;
}

export interface ShowSeasonOverride {
  id: number;
  source_show_tmdb_id: number;
  source_season_number: number;
  source_show_title: string | null;
  target_show_tmdb_id: number;
  target_season_number: number;
  target_show_title: string | null;
}

export interface UserList {
  id: number;
  name: string;
  description: string | null;
  privacy_level: PrivacyLevel;
  item_count: number;
  created_at: string;
  updated_at: string;
  preview_posters: { url: string; adult: boolean }[];
}

export interface PublicList extends UserList {
  username: string;
}

export interface ListItemEntry {
  id: number;
  list_id: number;
  added_at: string;
  sort_order: number;
  notes: string | null;
  media: MediaItem;
}

export interface ListDetail extends UserList {
  items: ListItemEntry[];
  is_owner: boolean;
}

// Main types

export type MediaType = "movie" | "series" | "episode" | "person" | "collection";

export interface UserProfile {
  id: number;
  email: string;
  username: string;
  display_name: string;
  role: string;
  is_admin: boolean;
  api_key: string;
  totp_enabled: boolean;
  created_at: string;
}

export interface AdminUser {
  id: number;
  username: string;
  email: string;
  is_admin: boolean;
  api_key: string;
  created_at: string;
}

export interface GlobalSettings {
  tmdb_api_key: string | null;
  radarr_url: string | null;
  radarr_token: string | null;
  radarr_root_folder: string | null;
  radarr_quality_profile: number | null;
  radarr_tags: number[] | null;
  sonarr_url: string | null;
  sonarr_token: string | null;
  sonarr_root_folder: string | null;
  sonarr_quality_profile: number | null;
  sonarr_tags: number[] | null;
  sonarr_season_folder: boolean;
  radarr_require_approval: boolean;
  sonarr_require_approval: boolean;
}

export interface MediaRequestItem {
  id: number;
  tmdb_id: number;
  media_type: string;
  title: string;
  poster_path: string | null;
  status: "pending" | "approved" | "rejected";
  reviewed_by: number | null;
  created_at: string;
  updated_at: string;
  user: { id: number; username: string; display_name: string };
}

export interface LoginResponse {
  access_token: string | null;
  token_type: string;
  requires_2fa: boolean;
  temp_token: string | null;
}

export interface TotpSetupData {
  provisioning_uri: string;
  secret: string;
}

export interface TotpBackupCode {
  id: number;
  code: string;
  used: boolean;
}

export interface TotpBackupCodesResponse {
  codes: TotpBackupCode[];
}

export interface OidcConfig {
  enabled: boolean;
  provider_name: string;
  disable_password_login: boolean;
}

export interface OidcAuthorizeResponse {
  auth_url: string;
  state: string;
}

export interface OidcExchangeResponse {
  access_token: string;
}

export type PrivacyLevel = "public" | "friends_only" | "private";

export interface UserPreferences {
  display_name: string | null;
  bio: string | null;
  country: string | null;
  movie_genres: string[];
  show_genres: string[];
  disliked_genres: string[];
  streaming_services: string[];
  content_language: string | null;
  metadata_language: string | null;
  privacy_level: PrivacyLevel;
  avatar_url: string | null;
}

export interface UserSettings {
  tmdb_api_key: string | null;
  has_effective_tmdb_key: boolean;
  has_global_tmdb_key: boolean;

  tvdb_api_key: string | null;
  has_effective_tvdb_key: boolean;
  has_global_tvdb_key: boolean;

  radarr_url: string | null;
  radarr_token: string | null;
  radarr_root_folder: string | null;
  radarr_quality_profile: number | null;
  radarr_tags: number[] | null;

  sonarr_url: string | null;
  sonarr_token: string | null;
  sonarr_root_folder: string | null;
  sonarr_quality_profile: number | null;
  sonarr_tags: number[] | null;

  // Trakt
  trakt_connected: boolean;
  trakt_sync_watched: boolean;
  trakt_sync_ratings: boolean;
  trakt_sync_lists: boolean;
  trakt_watchlist_split: boolean;
  trakt_push_watched: boolean;
  trakt_push_ratings: boolean;
  trakt_push_lists: boolean;
  trakt_scrobble: boolean;

  // Simkl
  simkl_client_id: string | null;
  simkl_connected: boolean;
  simkl_sync_watched: boolean;
  simkl_sync_ratings: boolean;
  simkl_sync_lists: boolean;
  simkl_push_watched: boolean;
  simkl_push_ratings: boolean;
  simkl_scrobble: boolean;

  // MDBList
  mdblist_api_key: string | null;
  mdblist_connected: boolean;
  mdblist_sync_watched: boolean;
  mdblist_sync_ratings: boolean;
  mdblist_sync_watchlist: boolean;
  mdblist_push_watched: boolean;
  mdblist_push_ratings: boolean;
  mdblist_push_watchlist: boolean;

  preferences: UserPreferences | null;
  blur_explicit: boolean;
  time_format_24h: boolean;
  use_hls_player: boolean;
}

export interface MediaServerConnection {
  id: number;
  user_id: number;
  type: "jellyfin" | "emby" | "plex" | "nuvio";
  name: string;
  url: string;
  token: string;
  server_user_id: string | null;
  server_username: string | null;
  sync_collection: boolean;
  sync_watched: boolean;
  sync_ratings: boolean;
  sync_playback: boolean;
  push_watched: boolean;
  push_collection: boolean;
  push_playback: boolean;
  push_ratings: boolean;
  auto_sync_interval: number | null;
  auto_push_interval: number | null;
  created_at: string;
}

export interface MediaServerConnectionCreate {
  type: "jellyfin" | "emby" | "plex" | "nuvio";
  name: string;
  url: string;
  token: string;
  server_user_id?: string | null;
  server_username?: string | null;
  sync_collection?: boolean;
  sync_watched?: boolean;
  sync_ratings?: boolean;
  sync_playback?: boolean;
  push_watched?: boolean;
  push_collection?: boolean;
  push_playback?: boolean;
  push_ratings?: boolean;
  auto_sync_interval?: number | null;
  auto_push_interval?: number | null;
}

export type MediaServerConnectionUpdate = Partial<Omit<MediaServerConnectionCreate, "type">>;

export interface ScrobbleConnection {
  id: number;
  user_id: number;
  type: "jellyfin" | "emby" | "plex";
  name: string;
  server_user_id: string | null;
  server_username: string | null;
  sync_collection: boolean;
  sync_watched: boolean;
  sync_playback: boolean;
  created_at: string;
}

export interface ScrobbleConnectionCreate {
  type: "jellyfin" | "emby" | "plex";
  name: string;
  server_user_id?: string | null;
  server_username?: string | null;
  sync_collection?: boolean;
  sync_watched?: boolean;
  sync_playback?: boolean;
}

export type ScrobbleConnectionUpdate = Pick<ScrobbleConnectionCreate, "sync_collection" | "sync_watched" | "sync_playback">;

export interface ServiceStatus {
  configured: boolean;
  connected: boolean;
  quality_profiles?: { id: number; name: string }[];
  root_folders?: { path: string; freeSpace: number }[];
  tags?: { id: number; label: string }[];
}

export interface ConnectionStatus {
  radarr: ServiceStatus;
  sonarr: ServiceStatus;
  trakt: ServiceStatus;
  simkl: ServiceStatus;
  mdblist: ServiceStatus;
}

export interface MediaItem {
  id: number | null;
  tmdb_id: number | null;
  tvdb_id?: number | null;
  type: MediaType;
  title: string;
  original_title?: string | null;
  overview?: string | null;
  poster_path: string | null;
  backdrop_path?: string | null;
  release_date?: string | null;
  tmdb_rating?: number | null;
  season_number?: number | null;
  episode_number?: number | null;
  runtime?: number | null;
  genres?: string[];
  cast?: CastMember[];
  crew?: { tmdb_id: number; name: string; job: string; profile_path?: string | null }[];
  tagline?: string | null;
  status?: string | null;
  original_language?: string | null;
  age_rating?: string | null;
  imdb_id?: string | null;
  adult?: boolean;
  show_id?: number | null;
  show_title?: string | null;
  show_tmdb_id?: number | null;
  show_tvdb_id?: number | null;
  show_poster_path?: string | null;
  show_backdrop_path?: string | null;
  next_up_hidden?: boolean;
  known_for_department?: string | null;
  in_library?: boolean;
  playable?: boolean;
  // Card action state
  watched?: boolean;
  watch_source?: string | null;
  watch_history?: {
    id: number;
    watched_at: string | null;
    watch_source: string | null;
  }[];
  in_lists?: number[];
  collection_pct?: number;
  watch_pct?: number;
  is_monitored?: boolean;
  request_enabled?: boolean;
  user_rating?: number | null;
  play_count?: number;
  library: {
    resolution: string;
    video_codec: string;
    audio_codec: string;
    audio_channels: string;
    audio_languages: string[];
    subtitle_languages: string[];
  } | null;
  where_to_watch?: { type: string; name: string; logo: string | null }[];
  collection?: {
    id: number;
    name: string;
    poster_path: string | null;
    backdrop_path: string | null;
    parts: MediaItem[];
  };
  production_companies?: ProductionCompany[];
  recommendations?: MediaItem[];
  release_dates?: { digital?: string | null; physical?: string | null } | null;
}

export interface SubtitleTrack {
  index: number;
  language: string | null;
  label: string | null;
  codec: string | null;
}

export interface PlaybackSource {
  connection_id: number;
  source: string;
  name: string;
  resolution: string | null;
  subtitles: SubtitleTrack[];
}

export interface ContinueWatchingItem {
  id: number;
  media: MediaItem;
  user_id: number;
  watched_at: string;
  progress_seconds: number | null;
  progress_percent: number | null;
  completed: boolean;
}

export interface CollectionDetail {
  id: number;
  name: string;
  overview: string | null;
  poster_path: string | null;
  backdrop_path: string | null;
  genres: string[];
  cast: { tmdb_id: number; name: string; profile_path: string | null; appearances: number }[];
  parts: MediaItem[];
}

export interface TvdbEpisode {
  tvdb_id: number | null;
  tmdb_id: number | null;
  show_tmdb_id: number | null;
  tmdb_season_number: number;
  tmdb_episode_number: number;
  season_number: number;
  episode_number: number;
  name: string | null;
  overview: string | null;
  air_date: string | null;
  runtime: number | null;
  image_url: string | null;
  id: number | null;
  in_library: boolean;
  watched: boolean;
  user_rating: number | null;
  in_lists: number[];
}

export interface TvdbEpisodeDetail {
  tvdb_id: number | null;
  tmdb_id: number | null;
  show_tmdb_id: number | null;
  tmdb_season_number: number;
  tmdb_episode_number: number;
  season_number: number;
  episode_number: number;
  name: string | null;
  overview: string | null;
  air_date: string | null;
  runtime: number | null;
  image_url: string | null;
  id: number | null;
  in_library: boolean;
  watched: boolean;
  user_rating: number | null;
  play_count: number;
  in_lists: number[];
  library: {
    resolution: string | null;
    video_codec: string | null;
    audio_codec: string | null;
    audio_channels: string | null;
    audio_languages: string[] | null;
    subtitle_languages: string[] | null;
  } | null;
  cast: { tmdb_id: null; person_id: number | null; name: string; character: string; profile_path: string | null }[];
  episodes: { episode_number: number; name: string | null }[];
  show: { id: number | null; tvdb_id: number; tmdb_id: number | null; episode_order: "tvdb"; title: string; poster_path: string | null; backdrop_path: string | null };
  season: { name: string; season_number: number; poster_path: string | null };
}

export interface TvdbSeason {
  tvdb_id: number;
  season_number: number;
  name: string;
  overview: string | null;
  tmdb_rating: number | null;
  poster_path: string | null;
  backdrop_path: string | null;
  air_date: string | null;
  episodes: TvdbEpisode[];
  season_in_library: boolean;
  season_watch_pct: number;
  season_watched: boolean;
  season_collection_pct: number;
  season_user_rating: number | null;
  show_in_library: boolean;
  show: {
    id: number | null;
    tvdb_id: number;
    tmdb_id: number | null;
    episode_order: "tvdb";
    title: string;
    poster_path: string | null;
    backdrop_path: string | null;
    seasons_meta: TvdbSeasonMeta[];
  };
}

export interface TvdbSeasonMeta {
  season_number: number;
  name: string;
  overview: string | null;
  tmdb_rating: number | null;
  poster_path: string | null;
  episode_count: number;
  air_date: string | null;
}

export interface TvdbShow {
  id: number | null;
  tvdb_id: number;
  tmdb_id: number | null;
  type: string;
  title: string;
  original_title: string | null;
  overview: string | null;
  poster_path: string | null;
  backdrop_path: string | null;
  first_air_date: string | null;
  last_air_date: string | null;
  status: string | null;
  tagline: null;
  tmdb_rating: number | null;
  age_rating: string | null;
  original_language: string | null;
  imdb_id: string | null;
  tmdb_id_cross: number | null;
  episode_order: "tvdb";
  genres: string[];
  network: string | null;
  networks: { id: null; name: string; logo_path: null; origin_country: null }[];
  seasons: TvdbSeasonMeta[];
  seasons_meta: TvdbSeasonMeta[];
  cast: { tmdb_id: null; person_id: number | null; name: string; character: string; profile_path: string | null }[];
  in_library: boolean;
  watched: boolean;
  in_lists: number[];
  collection_pct: number;
  is_monitored: boolean;
  request_enabled: boolean;
  request_status: string | null;
  user_rating: number | null;
  season_states: Record<number, SeasonState>;
  where_to_watch: { type: string; name: string; logo: string | null }[];
}

export interface Show {
  id: number | null;
  tmdb_id: number;
  tvdb_id?: number | null;
  episode_order: "tmdb" | "tvdb";
  title: string;
  original_title: string | null;
  overview: string;
  poster_path: string | null;
  backdrop_path: string | null;
  tmdb_rating: number;
  genres: string[];
  in_library: boolean;
  watched: boolean;
  in_lists: number[];
  collection_pct: number;
  is_monitored?: boolean;
  request_enabled?: boolean;
  seasons: Record<string, MediaItem[]>;
  seasons_meta: SeasonMeta[];
  season_states: Record<number, SeasonState>;
  cast: CastMember[];
  guest_stars: CastMember[];
  crew?: CrewCredit[];
  created_by?: { tmdb_id: number; name: string; profile_path?: string | null }[];
  networks: Network[];
  production_companies?: ProductionCompany[];  recommendations: MediaItem[];
  tagline: string | null;
  status: string | null;
  original_language?: string | null;
  age_rating?: string | null;
  imdb_id?: string | null;
  adult?: boolean;
  user_rating?: number | null;
  first_air_date: string | null;
  last_air_date: string | null;
  where_to_watch?: { type: string; name: string; logo: string | null }[];
  episode_count?: number;
  watched_count?: number;
  remaining_count?: number;
  total_runtime?: number | null;
  watched_runtime?: number | null;
  remaining_runtime?: number | null;
  remaining_runtime_estimated?: boolean;
  watch_start_date?: string | null;
  watch_end_date?: string | null;
  last_watched_at?: string | null;
}

export interface ProfileWatchedItem {
  tmdb_id: number;
  media_type: string;
  title: string;
  poster_path: string | null;
  backdrop_path: string | null;
  watched_at: string;
  show_title: string | null;
  show_tmdb_id: number | null;
  show_poster_path: string | null;
  season_number: number | null;
  episode_number: number | null;
}

export interface ProfileRatedItem {
  tmdb_id: number;
  media_type: string;
  title: string;
  poster_path: string | null;
  backdrop_path: string | null;
  user_rating: number;
}

export interface UserSearchResult {
  id: number;
  username: string;
  display_name: string;
  avatar_url: string | null;
  country: string | null;
  movies_watched: number;
  shows_watched: number;
  total_collected: number;
  total_rated: number;
  follower_count: number;
  is_following: boolean;
  is_self: boolean;
}

export interface ProfileFollowEntry {
  id: number;
  display_name: string;
  avatar_url: string | null;
}

export interface ProfileListItem {
  id: number;
  name: string;
  description: string | null;
  privacy_level: PrivacyLevel;
  item_count: number;
  updated_at: string;
  preview_posters: { url: string; adult: boolean }[];
}

export interface ProfileCommentItem {
  id: number;
  content: string;
  media_type: string;
  tmdb_id: number;
  season_number: number | null;
  episode_number: number | null;
  title: string | null;
  poster_path: string | null;
  created_at: string;
}

export interface PublicProfile {
  id: number;
  username: string;
  display_name: string;
  bio: string | null;
  country: string | null;
  movie_genres: string[];
  show_genres: string[];
  created_at: string;
  total_watched: number;
  total_collected: number;
  movies_watched: number;
  shows_watched: number;
  total_rated: number;
  avatar_url: string | null;
  recently_watched_movies: ProfileWatchedItem[];
  recently_watched_shows: ProfileWatchedItem[];
  top_rated_movies: ProfileRatedItem[];
  top_rated_shows: ProfileRatedItem[];
  recent_comments: ProfileCommentItem[];
  lists: ProfileListItem[];
  follower_count: number;
  following_count: number;
  followers: ProfileFollowEntry[];
  following: ProfileFollowEntry[];
  is_following: boolean;
}

export interface UserStats {
  movies_watched: number;
  shows_watched: number;
  episodes_watched: number;
  total_watch_minutes: number;
  watch_activity: { month: string; movies: number; episodes: number }[];
  rating_distribution: { rating: number; count: number }[];
  avg_movie_rating: number | null;
  avg_show_rating: number | null;
  movies_collected: number;
  shows_collected: number;
  episodes_collected: number;
  movies_watched_collected: number;
  movies_unwatched_collected: number;
  shows_watched_collected: number;
  shows_unwatched_collected: number;
  weekday_activity: { day: string; avg: number }[];
}

export interface Comment {
  id: number;
  user_id: number;
  username: string;
  display_name: string;
  avatar_url: string | null;
  user_is_public: boolean;
  content: string;
  is_spoiler: boolean;
  created_at: string;
  updated_at?: string | null;
}

export interface WatchlistMovie {
    id: number;
    title: string;
    year: number;
    tmdb_id: number;
    imdb_id: string | null;
    poster_path: string | null;
    backdrop_path: string | null;
    overview: string | null;
    tmdb_rating: number | null;
    runtime: number | null;
    release_date: string | null;
}

// API calls
// ── Physical collection ──────────────────────────────────────────────────────

/** A release in the physical collection, as the browser lists it. Empty
 * fields are left out of the list response. */
export interface PhysicalSummary {
  id: number;
  status: "owned" | "wishlist" | string;
  title: string;
  sort_title?: string;
  title_extension?: string;
  is_tv?: boolean;
  series?: string;
  tmdb_id?: number;
  tmdb_kind?: "movie" | "tv";
  release_year?: number;
  format?: string;
  edition?: string;
  distributor?: string;
  barcode?: string;
  package?: string;
  disc_count?: number;
  disc_release_date?: string;
  runtime?: number;
  purchase_date?: string;
  purchase_price?: number;
  store?: string;
  condition?: string;
  location?: string;
  index_no?: number;
  my_rating?: number;
  seen?: boolean;
  plays?: number;
  genres?: string[];
  regions?: string[];
  audience_rating?: string;
  imdb_rating?: number;
  director?: string;
  /** A box set or multi-film disc; or, for a film in one, the set's id. */
  is_set?: boolean;
  parent_id?: number;
  /** A sort title typed in (rather than worked out from the franchise). */
  own_sort?: boolean;
  /** The TMDB franchise a film belongs to. */
  franchise?: string;
  position?: number;
  tags?: string[];
  date_added?: string;
  cover?: string;
}

export interface PhysicalDetail extends PhysicalSummary {
  specs: Record<string, any>;
  current_value: number | null;
  owner: string | null;
  notes: string | null;
  viewing_date: string | null;
  seen_it: boolean;
  last_watched: string | null;
  cover_full: string | null;
  backdrop: string | null;
  backdrop_is_own: boolean;
  front_cover: string | null;
  poster: string | null;
  poster_is_own: boolean;
  /** A set's films, or for a film in a set, the films in that set. */
  contents: { id: number; title: string; title_extension?: string; release_year?: number; cover?: string; seen?: boolean; plays?: number; is_tv?: boolean; imdb_rating?: number }[];
  /** The sort title typed in, and the one worked out from the franchise. */
  own_sort_title?: string | null;
  auto_sort?: string | null;
  /** The set a film is in, with its shelf details. */
  parent: {
    id: number; title: string; cover: string | null; format: string | null; edition: string | null; barcode: string | null;
    location: string | null; purchase_date: string | null; purchase_price: number | null; store: string | null;
    condition: string | null; distributor: string | null;
  } | null;
  other_editions: { id: number; format: string | null; edition: string | null; status: string }[];
}

export interface PhysicalStats {
  owned: number;
  titles: number;
  sets: number;
  wishlist: number;
  discs: number;
  films: number;
  tv: number;
  seen: number;
  unseen: number;
  runtime_minutes: number;
  spent: number | null;
  priced_count: number;
  formats: { name: string; count: number }[];
  packages: { name: string; count: number }[];
  distributors: { name: string; count: number }[];
  stores: { name: string; count: number }[];
  conditions: { name: string; count: number }[];
  regions: { name: string; count: number }[];
  genres: { name: string; count: number }[];
  directors: { name: string; count: number }[];
  decades: { name: string; count: number }[];
  by_purchase_year: { year: number; count: number; spent: number }[];
}

export const api = {
  auth: {
    login: (body: FormData) =>
      post<LoginResponse>("/auth/login", body),
    register: (body: unknown) =>
      post<{ id: number; email: string; username: string }>("/auth/register", body),
    registrationStatus: () =>
      get<{ enabled: boolean; smtp_configured: boolean }>("/auth/registration-status"),
    hasUsers: () =>
      get<{ has_users: boolean }>("/auth/has-users"),
    activateEmail: (token: string) =>
      post<{ success: boolean }>(`/auth/activate/${token}`, undefined),
    forgotPassword: (email: string) =>
      post<{ message: string }>("/auth/forgot-password", { email }),
    resetPassword: (token: string, new_password: string) =>
      post<{ message: string }>(`/auth/reset-password/${token}`, { new_password }),
    me: (token: string) =>
      get<UserProfile>("/auth/me", undefined, token),
    getSettings: (token: string) =>
      get<UserSettings>("/auth/settings", undefined, token),
    updateSettings: (settings: Partial<UserSettings>, token: string) =>
      patch<UserSettings>("/auth/settings", settings, token),
    changePassword: (body: unknown, token: string) =>
      post<{ message: string }>("/auth/change-password", body, token),
    deleteAccount: (token: string) =>
      del<{ message: string }>("/auth/me", token),
    regenerateApiKey: (token: string) =>
      post<UserProfile>("/auth/api-key/regenerate", undefined, token),
    getConnections: (token: string) =>
      get<MediaServerConnection[]>("/auth/connections", undefined, token),
    createConnection: (body: MediaServerConnectionCreate, token: string) =>
      post<MediaServerConnection>("/auth/connections", body, token),
    updateConnection: (id: number, body: MediaServerConnectionUpdate, token: string) =>
      patch<MediaServerConnection>(`/auth/connections/${id}`, body, token),
    deleteConnection: (id: number, token: string) =>
      del<{ status: string }>(`/auth/connections/${id}`, token),
    getScrobbleConnections: (token: string) =>
      get<ScrobbleConnection[]>("/auth/scrobble-connections", undefined, token),
    createScrobbleConnection: (body: ScrobbleConnectionCreate, token: string) =>
      post<ScrobbleConnection>("/auth/scrobble-connections", body, token),
    updateScrobbleConnection: (id: number, body: ScrobbleConnectionUpdate, token: string) =>
      patch<ScrobbleConnection>(`/auth/scrobble-connections/${id}`, body, token),
    deleteScrobbleConnection: (id: number, token: string) =>
      del<{ status: string }>(`/auth/scrobble-connections/${id}`, token),
    testJellyfin: (url: string, token: string, jellyfinUserId: string | null, userToken: string) =>
      post<{ success: boolean; message: string }>(`/auth/test-jellyfin?url=${encodeURIComponent(url)}&token=${encodeURIComponent(token)}${jellyfinUserId ? `&user_id=${encodeURIComponent(jellyfinUserId)}` : ""}`, undefined, userToken),
    testEmby: (url: string, token: string, embyUserId: string | null, userToken: string) =>
      post<{ success: boolean; message: string }>(`/auth/test-emby?url=${encodeURIComponent(url)}&token=${encodeURIComponent(token)}${embyUserId ? `&user_id=${encodeURIComponent(embyUserId)}` : ""}`, undefined, userToken),
    testPlex: (url: string, token: string, userToken: string) =>
      post<{ success: boolean; message: string }>(`/auth/test-plex?url=${encodeURIComponent(url)}&token=${encodeURIComponent(token)}`, undefined, userToken),
    testRadarr: (url: string, token: string, userToken: string) =>
      post<{ success: boolean; message: string }>(`/auth/test-radarr?url=${encodeURIComponent(url)}&token=${encodeURIComponent(token)}`, undefined, userToken),
    getRadarrProfiles: (url: string, token: string, userToken: string) =>
      get<{ quality_profiles: any[]; root_folders: any[] }>(`/auth/radarr/profiles?url=${encodeURIComponent(url)}&token=${encodeURIComponent(token)}`, undefined, userToken),
    testSonarr: (url: string, token: string, userToken: string) =>
      post<{ success: boolean; message: string }>(`/auth/test-sonarr?url=${encodeURIComponent(url)}&token=${encodeURIComponent(token)}`, undefined, userToken),
    getSonarrProfiles: (url: string, token: string, userToken: string) =>
      get<{ quality_profiles: any[]; root_folders: any[]; language_profiles: any[] }>(`/auth/sonarr/profiles?url=${encodeURIComponent(url)}&token=${encodeURIComponent(token)}`, undefined, userToken),
    testTmdb: (key: string, userToken: string) =>
      post<{ success: boolean; message: string }>(`/auth/test-tmdb?key=${encodeURIComponent(key)}`, undefined, userToken),
    getConnectionStatus: (token: string) =>
      get<ConnectionStatus>("/auth/connection-status", undefined, token),
    totp2faSetup: (token: string) =>
      post<TotpSetupData>("/auth/2fa/setup", undefined, token),
    totp2faEnable: (body: { secret: string; code: string }, token: string) =>
      post<TotpBackupCodesResponse>("/auth/2fa/enable", body, token),
    totp2faDisable: (body: { code: string }, token: string) =>
      post<{ status: string }>("/auth/2fa/disable", body, token),
    totp2faBackupCodes: (token: string) =>
      get<TotpBackupCodesResponse>("/auth/2fa/backup-codes", undefined, token),
    totp2faVerifyLogin: (body: { temp_token: string; code: string }) =>
      post<LoginResponse>("/auth/2fa/verify-login", body),
    oidcConfig: () =>
      get<OidcConfig>("/auth/oidc/config"),
    oidcAuthorize: () =>
      get<OidcAuthorizeResponse>("/auth/oidc/authorize"),
    oidcExchange: (code: string) =>
      post<OidcExchangeResponse>("/auth/oidc/exchange", { code }),
  },

  trakt: {
    deviceStart: (token: string) =>
      post<{ user_code: string; verification_url: string; expires_in: number; interval: number }>("/trakt/auth/device/start", undefined, token),
    devicePoll: (token: string) =>
      post<{ status: "pending" | "connected" }>("/trakt/auth/device/poll", undefined, token),
    disconnect: (token: string) =>
      del<{ status: string }>("/trakt/auth/disconnect", token),
    sync: (token: string) =>
      post<{ status: string; job_id: number; message: string }>("/trakt/sync", undefined, token),
  },

  simkl: {
    pinStart: (token: string) =>
      post<{ user_code: string; url: string; expires_in: number; interval: number }>("/simkl/auth/pin/start", undefined, token),
    pinPoll: (token: string) =>
      post<{ status: "pending" | "connected" }>("/simkl/auth/pin/poll", undefined, token),
    disconnect: (token: string) =>
      del<{ status: string }>("/simkl/auth/disconnect", token),
    sync: (token: string) =>
      post<{ status: string; job_id: number; message: string }>("/simkl/sync", undefined, token),
    push: (token: string) =>
      post<{ status: string; message: string }>("/simkl/push", undefined, token),
  },

  mdblist: {
    sync: (token: string) =>
      post<{ status: string; job_id: number; message: string }>("/mdblist/sync", undefined, token),
    push: (token: string) =>
      post<{ status: string; job_id: number; message: string }>("/mdblist/push", undefined, token),
  },

  media: {
    list: (params?: { type?: string; sort?: string; page?: number; genre?: string[]; year?: number[]; watched?: string[] }, token?: string) =>
      get<{ page: number; page_size: number; total_pages: number; total_results: number; results: MediaItem[] }>("/media", params, token),

    years: (type: string, token?: string) =>
      get<{ years: number[] }>("/media/years", { type }, token),

    get: (type: string, tmdbId: number, token?: string) =>
      get<MediaItem>(`/media/${type}/${tmdbId}`, undefined, token),

    // A movie that isn't on TMDB, from its stored details (see /movie/local/[id]).
    getLocal: (mediaId: number, token?: string) =>
      get<any>(`/media/local/${mediaId}`, undefined, token),

    getRecommendations: (type: string, tmdbId: number, token?: string) =>
      get<{ results: MediaItem[] }>(`/media/${type}/${tmdbId}/recommendations`, undefined, token),

    getPerson: (
      personId: number,
      page: number = 1,
      token?: string,
      category: string = "acting"
    ) =>
      get<PersonDetail>(
        `/media/person/${personId}`,
        { page, category },
        token
      ),

    getCollection: (collectionId: number, token?: string) =>
      get<CollectionDetail>(`/media/collection/${collectionId}`, undefined, token),

    tmdbList: (params: { type: string; category?: string; page?: number; genre?: string; year?: number; min_rating?: number; status?: string }, token?: string) =>
      get<{ results: MediaItem[]; page: number; total_pages: number; total_results: number }>("/media/tmdb/list", params, token),

    search: (q: string, type?: string, page: number = 1, year?: number, token?: string, inLibrary?: boolean) =>
      get<{ results: MediaItem[]; page: number; total_pages: number; total_results: number }>("/media/search", { q, ...(type ? { type } : {}), page, ...(year ? { year } : {}), ...(inLibrary ? { in_library: true } : {}) }, token),

    searchTvdb: (q: string, token?: string) =>
      get<{ tvdb_id: number; title: string; overview: string | null; year: string | null; image_url: string | null; status: string | null; network: string | null }[]>("/media/search-tvdb", { q }, token),

    recentlyAdded: (type?: string, token?: string) =>
      get<{ results: MediaItem[] }>("/media/recently-added", type ? { type } : {}, token),

    onAirToday: (page: number = 1, token?: string) =>
      get<{ results: MediaItem[]; page: number; total_pages: number; total_results: number }>("/media/on-air-today", { page }, token),

    airingTodayCollected: (token?: string) =>
      get<{ results: MediaItem[] }>("/media/airing-today/collected", {}, token),

    trendingMovies: (page: number = 1, token?: string) =>
      get<{ results: MediaItem[]; page: number; total_pages: number; total_results: number }>("/media/trending/movies", { page }, token),

    trendingShows: (page: number = 1, token?: string) =>
      get<{ results: MediaItem[]; page: number; total_pages: number; total_results: number }>("/media/trending/shows", { page }, token),

    nowPlaying: (token?: string) =>
      get<{ results: MediaItem[] }>("/media/now-playing", {}, token),

    upcomingMovies: (token?: string) =>
      get<{ results: MediaItem[] }>("/media/upcoming", {}, token),

    onAirThisWeek: (token?: string) =>
      get<{ results: MediaItem[] }>("/media/on-air-this-week", {}, token),

    hiddenGems: (type: string = "movie", token?: string) =>
      get<{ results: MediaItem[] }>("/media/hidden-gems", { type }, token),

    recommended: (token?: string) =>
      get<{ results: MediaItem[] }>("/media/recommended", {}, token),

    forYou: (token?: string) =>
      get<{ results: MediaItem[] }>("/media/for-you", {}, token),

    collect: (body: { tmdb_id: number; media_type: string }, token: string) =>
      post<{ status: string; message: string }>("/media/collect", body, token),

    request: (type: string, tmdbId: number, token: string) =>
      post<{ status: string; movie?: any; series?: any }>(`/media/${type}/${tmdbId}/request`, undefined, token),

    uncollect: (tmdbId: number, mediaType: string, token: string) =>
      del<{ status: string }>(`/media/collect?tmdb_id=${tmdbId}&media_type=${mediaType}`, token),

    refreshMovie: (tmdbId: number, token: string) =>
      post<{ message: string }>(`/media/movie/${tmdbId}/refresh`, undefined, token),

    playbackSources: (type: string, tmdbId: number, token: string) =>
      get<PlaybackSource[]>(`/media/playback/${type}/${tmdbId}`, undefined, token),
  },

  shows: {
    list: (params?: { sort?: string; page?: number; page_size?: number; genre?: string[]; year?: number[]; status?: string[]; watched?: string[] }, token?: string) =>
      get<{ page: number; page_size: number; total_results: number; total_pages: number; results: any[] }>("/shows", params, token),

    progress: (token?: string) =>
      get<{ results: Show[]; total_results: number }>("/shows/progress", undefined, token),

    years: (token?: string) =>
      get<{ years: number[] }>("/shows/years", undefined, token),

    get: (seriesTmdbId: number, token?: string) =>
      get<Show>(`/shows/${seriesTmdbId}`, undefined, token),

    getRecommendations: (seriesTmdbId: number, token?: string) =>
      get<{ results: MediaItem[] }>(`/shows/${seriesTmdbId}/recommendations`, undefined, token),

    getSeason: (seriesTmdbId: number, seasonNumber: number, token?: string) =>
      get<Season>(`/shows/${seriesTmdbId}/season/${seasonNumber}`, undefined, token),

    getEpisode: (seriesTmdbId: number, seasonNumber: number, episodeNumber: number, token?: string) =>
      get<EpisodeDetail>(`/shows/${seriesTmdbId}/season/${seasonNumber}/${episodeNumber}`, undefined, token),

    refreshMetadata: (seriesTmdbId: number, token: string) =>
      post<{ message: string }>(`/shows/${seriesTmdbId}/refresh`, undefined, token),

    setEpisodeOrder: (seriesTmdbId: number, episodeOrder: "tmdb" | "tvdb", token: string, forceRefresh = false) =>
      post<{
        episode_order: "tmdb" | "tvdb";
        series_tmdb_id: number;
        tvdb_id: number | null;
        redirect: string;
        mapping: { matched: number; tmdb_episodes: number; unmatched: number } | null;
      }>(
        `/shows/${seriesTmdbId}/episode-order`,
        { episode_order: episodeOrder, force_refresh: forceRefresh },
        token,
      ),

    getTvdb: (tvdbId: number, token?: string) =>
      get<TvdbShow>(`/shows/tvdb/${tvdbId}`, undefined, token),

    getTvdbSeason: (tvdbId: number, seasonNumber: number, token?: string) =>
      get<TvdbSeason>(`/shows/tvdb/${tvdbId}/season/${seasonNumber}`, undefined, token),

    getTvdbEpisode: (tvdbId: number, seasonNumber: number, episodeNumber: number, token?: string) =>
      get<TvdbEpisodeDetail>(`/shows/tvdb/${tvdbId}/season/${seasonNumber}/episode/${episodeNumber}`, undefined, token),
  },

  history: {
    list: (params?: { page?: number; page_size?: number; type?: string }, token?: string) =>
      get<{ page: number; page_size: number; total_pages: number; total_results: number; results: WatchEvent[] }>("/history", params, token),

    markAsWatched: (body: { tmdb_id: number; media_type: string; watched_at?: string | null; completed?: boolean }, token: string) =>
      post<{ message: string }>("/history", body, token),

    unwatchItem: (tmdbId: number, mediaType: string, token: string) =>
      del<{ status: string }>(`/history/item?tmdb_id=${tmdbId}&media_type=${mediaType}`, token),

    markSeasonWatched: (body: { series_tmdb_id: number; season_number: number }, token: string) =>
      post<{ status: string; count: number }>("/history/season", body, token),

    unmarkSeasonWatched: (seriesTmdbId: number, seasonNumber: number, token: string) =>
      del<{ status: string }>(`/history/season?series_tmdb_id=${seriesTmdbId}&season_number=${seasonNumber}`, token),

    markShowWatched: (body: { series_tmdb_id: number }, token: string) =>
      post<{ status: string; count: number }>("/history/show-all", body, token),

    unmarkShowWatched: (seriesTmdbId: number, token: string) =>
      del<{ status: string }>(`/history/show-all?series_tmdb_id=${seriesTmdbId}`, token),

    continueWatching: (token?: string) =>
      get<{ continue_watching: ContinueWatchingItem[] }>("/history/continue-watching", undefined, token),

    nextUp: (token?: string, limit?: number, includeHidden?: boolean) =>
      get<{ next_up: MediaItem[] }>("/history/next-up", { ...(limit ? { limit } : {}), ...(includeHidden ? { include_hidden: true } : {}) }, token),

    hideNextUp: (showId: number, token: string) =>
      post<{ status: string }>("/history/next-up/hide", { show_id: showId }, token),

    unhideNextUp: (showId: number, token: string) =>
      del<{ status: string }>(`/history/next-up/hide?show_id=${showId}`, token),
  },

  dashboard: {
    stats: (token?: string) =>
      get("/dashboard/stats", undefined, token),

    hero: (token?: string) =>
      get("/dashboard/hero", undefined, token),

    watchlist: (token?: string) =>
      get("/dashboard/watchlist", undefined, token),

    last30: (token: string) =>
      get("/dashboard/last30", undefined, token),
  },

  watchlist: {
    getAll: (token: string) =>
      get<WatchlistMovie[]>("/watchlist", undefined, token),
  },

  physical: {
    items: (token?: string) => get<{ items: PhysicalSummary[] }>("/physical/items", undefined, token),
    item: (id: number, token?: string) => get<PhysicalDetail>(`/physical/items/${id}`, undefined, token),
    create: (fields: Record<string, unknown>, token?: string) => post<{ id: number }>("/physical/items", fields, token),
    update: (id: number, fields: Record<string, unknown>, token?: string) => patch<{ id: number }>(`/physical/items/${id}`, fields, token),
    remove: (id: number, token?: string) => del<{ deleted: number }>(`/physical/items/${id}`, token),
    stats: (token?: string) => get<PhysicalStats>("/physical/stats", undefined, token),
    options: (token?: string) => get<Record<string, string[]>>("/physical/options", undefined, token),
    lookup: (params: { barcode?: string; q?: string; tmdb_id?: number; kind?: "movie" | "tv" }, token?: string) =>
      get<{
        product: { title?: string; brand?: string; images?: string[]; already?: { id: number; title: string; status: string } } | null;
        query: string | null;
        results: { kind: "movie" | "tv"; tmdb_id: number; title: string; year: string | null; poster: string | null }[];
      }>("/physical/lookup", params, token),
  },

  calendar: {
    upcoming: (
      token?: string,
      days = 7,
      fromWeekStart = false,
    ) =>
      get<{
        days: number;
        start_date?: string;
        today?: string;
        end_date?: string;
        episodes: Array<{
          id: number;
          show_id: number;
          show_title: string | null;
          title: string | null;
          season: number | null;
          episode: number | null;
          air_date: string;
          air_time?: string | null;
          poster_path: string | null;
          backdrop_path: string | null;
          show_poster_path: string | null;
          runtime: number | null;
          rating: number | null;
          tmdb_id: number | null;
          network?: string | null;
          season_poster_path?: string | null;
          show_tmdb_id?: number | null;
          badge?: string | null;
          watched?: boolean;
        }>;
        // Release dates of films on the user's watchlist and lists, and
        // recent films they've watched.
        movies?: Array<{
          tmdb_id: number;
          title: string | null;
          poster_path: string | null;
          date: string;
          kind: "cinema" | "digital" | "streaming" | "disc";
          label: string;
          country: string | null;
          watched: boolean;
        }>;
      }>(`/calendar/upcoming?days=${days}${fromWeekStart ? "&from_week_start=true" : ""}`, undefined, token),
  },

  lists: {
    getAll: (token: string) =>
      get<{ lists: UserList[] }>("/lists", undefined, token),
    getPublic: (token: string) =>
      get<{ lists: PublicList[] }>("/lists/public", undefined, token),
    create: (body: { name: string; description?: string; privacy_level?: PrivacyLevel }, token: string) =>
      post<UserList>("/lists", body, token),
    get: (id: number, token: string) =>
      get<ListDetail>(`/lists/${id}`, undefined, token),
    update: (id: number, body: { name?: string; description?: string; privacy_level?: PrivacyLevel }, token: string) =>
      patch<UserList>(`/lists/${id}`, body, token),
    delete: (id: number, token: string) =>
      del<{ message: string }>(`/lists/${id}`, token),
    addItem: (listId: number, body: { tmdb_id: number; media_type: string }, token: string) =>
      post<ListItemEntry>(`/lists/${listId}/items`, body, token),
    removeItem: (listId: number, itemId: number, token: string) =>
      del<{ message: string }>(`/lists/${listId}/items/${itemId}`, token),
  },

  sync: {
    jellyfin: (params?: { movie_limit?: number; show_limit?: number }, token?: string) =>
      post<{ status: string; job_id: number; message: string }>("/sync/jellyfin", params, token),
    emby: (params?: { movie_limit?: number; show_limit?: number }, token?: string) =>
      post<{ status: string; job_id: number; message: string }>("/sync/emby", params, token),
    plex: (params?: { movie_limit?: number; show_limit?: number }, token?: string) =>
      post<{ status: string; job_id: number; message: string }>("/sync/plex", params, token),
    syncConnection: (connectionId: number, params?: { movie_limit?: number; show_limit?: number }, token?: string) =>
      post<{ status: string; job_id: number; message: string }>(`/sync/connection/${connectionId}`, params, token),
    status: (token: string) =>
      get<SyncJob[]>("/sync/status", undefined, token),
    getConnectionLibraries: (connectionId: number, token: string) =>
      get<{ libraries: { id?: string; key?: string; name: string; type: string; selected: boolean }[]; all_selected: boolean }>(`/sync/connection/${connectionId}/libraries`, undefined, token),
    saveConnectionLibraries: (connectionId: number, body: { library_ids?: string[]; library_keys?: string[] }, token: string) =>
      put<{ saved: number }>(`/sync/connection/${connectionId}/libraries`, body, token),
    scanLibraries: (connectionId: number, token: string) =>
      post<{ status: string; message: string }>(`/sync/connection/${connectionId}/scan`, undefined, token),
    getSeasonOverrides: (token: string) =>
      get<ShowSeasonOverride[]>("/sync/season-overrides", undefined, token),
  },

  profile: {
    get: (token: string) =>
      get<UserPreferences>("/profile/me", undefined, token),
    getPublic: (userId: number, token?: string) =>
      get<PublicProfile>(`/profile/${userId}`, undefined, token),
    update: (body: Partial<UserPreferences>, token: string) =>
      patch<UserPreferences>("/profile/me", body, token),
    uploadAvatar: (formData: FormData, token: string) =>
      request<{ avatar_url: string }>("/profile/me/avatar", "POST", undefined, formData, token),
    deleteAvatar: (token: string) =>
      del<{ status: string }>("/profile/me/avatar", token),
    follow: (userId: number, token: string) =>
      post<{ status: string }>(`/profile/${userId}/follow`, undefined, token),
    unfollow: (userId: number, token: string) =>
      del<{ status: string }>(`/profile/${userId}/follow`, token),
    searchUsers: (q: string, token?: string) =>
      get<{ results: UserSearchResult[] }>("/profile/search", { q }, token),
    getStats: (userId: number, token?: string) =>
      get<UserStats>(`/profile/${userId}/stats`, undefined, token),
  },

  comments: {
    list: (params: { media_type: string; tmdb_id: number; season_number?: number; episode_number?: number }, token?: string) =>
      get<Comment[]>("/comments", params, token),
    create: (body: { media_type: string; tmdb_id: number; season_number?: number; episode_number?: number; content: string }, token: string) =>
      post<Comment>("/comments", body, token),
    update: (id: number, content: string, token: string) =>
      patch<{ id: number; content: string; updated_at: string | null }>(`/comments/${id}`, { content }, token),
    delete: (id: number, token: string) =>
      del<{ message: string }>(`/comments/${id}`, token),
  },

  admin: {
    getSettings: (token: string) =>
      get<GlobalSettings>("/admin/settings", undefined, token),
    updateSettings: (body: Partial<GlobalSettings>, token: string) =>
      patch<GlobalSettings>("/admin/settings", body, token),
    listUsers: (token: string) =>
      get<AdminUser[]>("/admin/users", undefined, token),
    toggleAdmin: (userId: number, token: string) =>
      patch<AdminUser>(`/admin/users/${userId}/toggle-admin`, undefined, token),
    deleteUser: (userId: number, token: string) =>
      del<{ status: string }>(`/admin/users/${userId}`, token),
    getPendingCount: (token: string) =>
      get<{ pending: number }>("/admin/requests/pending-count", undefined, token),
    getRequests: (token: string) =>
      get<MediaRequestItem[]>("/admin/requests", undefined, token),
    approveRequest: (requestId: number, token: string) =>
      post<{ status: string }>(`/admin/requests/${requestId}/approve`, undefined, token),
    rejectRequest: (requestId: number, token: string) =>
      post<{ status: string }>(`/admin/requests/${requestId}/reject`, undefined, token),
  },
};

export function tmdbImageUrl(path: string | null | undefined, size: string = "w500"): string | null {
  if (!path) return null;
  if (path.startsWith("http://") || path.startsWith("https://")) {
    const match = /image\.tmdb\.org\/t\/p\/([^/]+)(\/.+)$/.exec(path);
    if (match) {
      return `/api/proxy/media/image/${match[1]}${match[2]}`;
    }
    return path;
  }
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  return `/api/proxy/media/image/${size}${cleanPath}`;
}

