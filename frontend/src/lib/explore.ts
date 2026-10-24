import { api, type MediaItem } from "./api";

// TMDB list pages hold 20 items, which leaves a part-filled last row in the
// Explore grids. Show 24 per page instead (fills every row at 2, 3, 4 and 6
// columns) by stitching together the one or two TMDB pages each page covers.
export const EXPLORE_PER_PAGE = 24;
const TMDB_PER_PAGE = 20;
const TMDB_MAX_PAGES = 500;

type ListParams = Omit<Parameters<typeof api.media.tmdbList>[0], "page"> & {
  watched?: string;
};

export interface ExplorePage {
  results: MediaItem[];
  total_pages: number;
  page: number;
}

export async function fetchExplorePage(
  params: ListParams,
  page: number,
  token?: string,
): Promise<ExplorePage> {
  const fetchTmdbPage = (tmdbPage: number) =>
    api.media.tmdbList({ ...params, page: tmdbPage } as any, token);

  // With a watch status filter the backend pages the filtered list itself,
  // EXPLORE_PER_PAGE at a time.
  if (params.watched) {
    const data = await fetchTmdbPage(page);
    return { results: data.results, page, total_pages: data.total_pages };
  }

  const first = (page - 1) * EXPLORE_PER_PAGE;
  const firstTmdbPage = Math.floor(first / TMDB_PER_PAGE) + 1;
  const lastTmdbPage = Math.min(
    Math.floor((first + EXPLORE_PER_PAGE - 1) / TMDB_PER_PAGE) + 1,
    TMDB_MAX_PAGES,
  );
  const tmdbPages = await Promise.all(
    Array.from({ length: lastTmdbPage - firstTmdbPage + 1 }, (_, i) =>
      fetchTmdbPage(firstTmdbPage + i),
    ),
  );
  const offset = first - (firstTmdbPage - 1) * TMDB_PER_PAGE;
  const pick = () => {
    // Popular lists can shift between requests, repeating an item across
    // TMDB pages; show each one once.
    const seen = new Set<number>();
    return tmdbPages
      .flatMap((p) => p.results)
      .slice(offset)
      .filter((item) => !seen.has(item.tmdb_id) && seen.add(item.tmdb_id))
      .slice(0, EXPLORE_PER_PAGE);
  };
  let results = pick();
  // A dropped repeat leaves the page one short; top it up from the next TMDB page.
  const nextTmdbPage = lastTmdbPage + 1;
  if (
    results.length < EXPLORE_PER_PAGE &&
    nextTmdbPage <= Math.min(tmdbPages[0]?.total_pages ?? 0, TMDB_MAX_PAGES)
  ) {
    tmdbPages.push(await fetchTmdbPage(nextTmdbPage));
    results = pick();
  }
  const totalResults = Math.min(
    tmdbPages[0]?.total_results ?? 0,
    (tmdbPages[0]?.total_pages ?? 0) * TMDB_PER_PAGE,
    TMDB_MAX_PAGES * TMDB_PER_PAGE,
  );
  return { results, page, total_pages: Math.ceil(totalResults / EXPLORE_PER_PAGE) };
}
