// Today's holiday theme from the backend (core/holidays.py), fetched once a
// page. ?holiday=YYYY-MM-DD on any page previews that day's theme.
import type { AstroGlobal } from "astro";

export interface HolidayTheme {
  key: string;
  name: string;
  greeting: string;
  decoration: string;
  /** The red scale it replaces, 300 to 700. */
  accent: string[];
  second: string;
}

export async function getHoliday(astro: AstroGlobal): Promise<HolidayTheme | null> {
  const locals = astro.locals as { holiday?: Promise<HolidayTheme | null> };
  if (!locals.holiday) {
    const day = astro.url.searchParams.get("holiday");
    const query = day && /^\d{4}-\d{2}-\d{2}$/.test(day) ? `?day=${day}` : "";
    locals.holiday = fetch(`http://127.0.0.1:8000/dashboard/theme${query}`)
      .then((res) => (res.ok ? res.json() : { theme: null }))
      .then((data) => data.theme ?? null)
      .catch(() => null);
  }
  return locals.holiday;
}

/** The CSS variables that swap Watchd's red for the holiday's colours. */
export function holidayStyle(theme: HolidayTheme | null): string {
  if (!theme) return "";
  const [c300, c400, c500, c600, c700] = theme.accent;
  return `--watchd-red-300:${c300};--watchd-red-400:${c400};--watchd-red-500:${c500};--watchd-red-600:${c600};--watchd-red-700:${c700};--holiday-second:${theme.second}`;
}
