// Watch times come from the API as naive UTC ("2026-10-18T13:00:00"). Pages
// render them in a <time data-local="date|time"> element: the server formats it
// in the app's home time zone (the server itself runs in UTC), then Base.astro
// re-formats it in the browser's own zone, matching the Watch History popup.

/** Use this as `timeZone` for any date/time formatted during server rendering. */
export const HOME_TIME_ZONE = "Europe/Malta";

/** Mark a naive UTC timestamp as UTC so Date parses it correctly anywhere. */
export function utcIso(value: string): string {
  // Postgres gives microseconds; some browsers (Safari) only parse milliseconds.
  const trimmed = value.replace(/(\.\d{3})\d+/, "$1");
  return /(Z|[+-]\d\d:?\d\d)$/.test(trimmed) ? trimmed : `${trimmed}Z`;
}

export const WATCH_DATE_FORMAT: Intl.DateTimeFormatOptions = {
  month: "short",
  day: "numeric",
  year: "numeric",
};

export const WATCH_TIME_FORMAT: Intl.DateTimeFormatOptions = {
  hour: "numeric",
  minute: "2-digit",
};

export function formatWatchDate(value: string): string {
  return new Date(utcIso(value)).toLocaleDateString("en-US", {
    ...WATCH_DATE_FORMAT,
    timeZone: HOME_TIME_ZONE,
  });
}

export function formatWatchTime(value: string): string {
  return new Date(utcIso(value)).toLocaleTimeString("en-US", {
    ...WATCH_TIME_FORMAT,
    timeZone: HOME_TIME_ZONE,
  });
}
