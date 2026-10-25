// How the physical collection is filed and found, as plain functions the
// collection page uses (and the tests check): box sets holding their films,
// shelf order, folders and search.
import type { PhysicalSummary } from "../api";

type Item = PhysicalSummary;
export type Kids = (i: Item) => Item[];

/** What's narrowing the collection: search words, first letter, folder. */
export interface Filters {
  q: string;
  letter: string;
  group: string;
  folder: string | null;
}

/** Box sets and multi-film discs are one entry on the shelf, with their films
 *  inside (in order). A set counts as seen once all its films are, and takes
 *  its earliest film's year when it has none of its own. Returns the lookup
 *  of a set's films. */
export function prepareSets(all: Item[]): Kids {
  const kidsOf = new Map<number, Item[]>();
  for (const i of all) if (i.parent_id) kidsOf.set(i.parent_id, [...(kidsOf.get(i.parent_id) ?? []), i]);
  for (const k of kidsOf.values()) k.sort((a, b) => (a.position ?? 1e9) - (b.position ?? 1e9));
  const kids: Kids = (i) => kidsOf.get(i.id) ?? [];
  for (const i of all) {
    if (!i.is_set) continue;
    const k = kids(i);
    i.seen = k.length > 0 && k.every((x) => x.seen);
    const years = k.map((x) => x.release_year).filter((y): y is number => !!y);
    if (!i.release_year && years.length) i.release_year = Math.min(...years);
  }
  return kids;
}

/** "2 films", "10 seasons", "5 titles" (a mix). */
export function setSize(k: Item[]): string {
  const word = k.every((x) => x.is_tv) ? "season" : k.some((x) => x.is_tv) ? "title" : "film";
  return `${k.length} ${word}${k.length === 1 ? "" : "s"}`;
}

/** "MPAAPG-13" -> "PG-13"; "BBFC15" -> "BBFC 15". */
export function ageRating(r?: string | null): string {
  if (!r) return "";
  const m = /^(MPAA|BBFC|FSK|ACB|CHVRS|OFLC|KMRB)(.+)$/.exec(r);
  return m ? (m[1] === "MPAA" ? m[2] : `${m[1]} ${m[2]}`) : r;
}

export const formatClass = (f?: string) =>
  (f || "").toLowerCase().includes("4k") ? "uhd" : (f || "").includes("3D") ? "three-d" : (f || "").toLowerCase().includes("dvd") ? "dvd" : "bd";
export const formatLabel = (f?: string) => (f === "4K UHD" ? "4K" : f === "Blu-ray 3D" ? "3D" : f || "");

// ── Shelf order ──────────────────────────────────────────────────────────────

/** Titles sort and file as on the shelf: without a leading article, with "&"
 *  read as "and". Ones starting with punctuation ("The 'Burbs", "(500)
 *  Days...") go first, in the # pile; a Spanish "¡" or "¿" is part of the
 *  word, so "¡Three Amigos!" files under T. */
export function titleParts(i: Item): { punct: number | null; text: string } {
  const t = (i.sort_title || i.title).replace(/&/g, " and ").replace(/^(the|a|an)\s+/i, "").replace(/^[¡¿]+/, "")
    .replace(/\s+/g, " ").trim().toLowerCase();
  const punct = /^[^\p{L}\p{N}]/u.test(t) ? t.charCodeAt(0) : null;
  return { punct, text: t.replace(/^[^\p{L}\p{N}]+/u, "") };
}

/** A box set files where its first film does, unless it has a sort title of
 *  its own. */
const shelfItem = (i: Item, kids: Kids) => (i.is_set && !i.own_sort && kids(i).length ? kids(i)[0] : i);

export function sortKey(i: Item, kids: Kids): string {
  const { punct, text } = titleParts(shelfItem(i, kids));
  return punct == null ? `1 ${text}` : `0 ${String(punct).padStart(5, "0")} ${text}`;
}

/** Text order with numbers in order: 2 before 10. */
export const byText = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });

/** The letter-bar pile an entry is in: A–Z, or # for numbers and punctuation. */
export function firstLetter(i: Item, kids: Kids): string {
  const { punct, text } = titleParts(shelfItem(i, kids));
  const c = text.normalize("NFD").charAt(0).toUpperCase();
  return punct == null && /[A-Z]/.test(c) ? c : "#";
}

/** Sorts by `sort` (a field, or "title" for shelf order) in `dir` (1 up, -1
 *  down). `value` gives a column's own sort value where it has one. Blanks
 *  count as the lowest value: first going up, last going down. Ties fall back
 *  to shelf order. */
export function sortItems(items: Item[], sort: string, dir: number, kids: Kids, value?: (i: Item) => unknown): Item[] {
  return [...items].sort((a, b) => {
    let x: any, y: any;
    if (sort === "title") { x = sortKey(a, kids); y = sortKey(b, kids); }
    else if (value) { x = value(a) || null; y = value(b) || null; }
    else { x = (a as any)[sort]; y = (b as any)[sort]; }
    if (x === "") x = null;
    if (y === "") y = null;
    const shelf = () => byText(sortKey(a, kids), sortKey(b, kids));
    if (x == null && y == null) return shelf();
    if (x == null) return -dir;
    if (y == null) return dir;
    const c = typeof x === "number" ? x - y : byText(String(x), String(y));
    return (c || shelf()) * dir;
  });
}

// ── Folders and search ───────────────────────────────────────────────────────

/** An entry's folders under a grouping (some have several). */
export function folderValues(i: Item, group: string): string[] {
  switch (group) {
    case "genres": return i.genres?.length ? i.genres : ["(none)"];
    case "regions": return i.regions?.length ? i.regions : ["(none)"];
    case "tags": return i.tags?.length ? i.tags : ["(none)"];
    case "director": return i.director ? i.director.split("; ") : ["(none)"];
    case "audience_rating": return [ageRating(i.audience_rating) || "(none)"];
    case "purchase_year": return [i.purchase_date ? i.purchase_date.slice(0, 4) : "(none)"];
    case "decade": return [i.release_year ? `${Math.floor(i.release_year / 10) * 10}s` : "(none)"];
    case "seen": return [i.seen ? "Seen" : "Not seen"];
    case "kind": return [i.is_tv ? "TV" : "Film"];
    case "in_set": return [i.is_set ? i.title : "(none)"];
    case "franchise": return [i.franchise || "(none)"];
    default: {
      const v = (i as unknown as Record<string, unknown>)[group];
      return [v ? String(v) : "(none)"];
    }
  }
}

/** A set is in every folder its films are in (and its own). */
export function folderOf(i: Item, group: string, kids: Kids): string[] {
  if (!i.is_set || group === "seen" || group === "in_set") return folderValues(i, group);
  const values = new Set([i, ...kids(i)].flatMap((x) => folderValues(x, group)).filter((v) => v !== "(none)"));
  return values.size ? [...values] : ["(none)"];
}

/** Every search word appears in the entry's title, edition, barcode... */
export function qMatch(i: Item, q: string): boolean {
  if (!q) return true;
  const hay = [i.title, i.title_extension, i.edition, i.barcode, i.director, i.distributor, i.series, i.store, ...(i.tags || [])]
    .filter(Boolean).join(" ").toLowerCase();
  return q.toLowerCase().split(/\s+/).every((w) => hay.includes(w));
}

/** Whether an entry shows under the filters (a set shows when any of its films
 *  matches the search). `skipFolder` counts it for every folder. */
export function matches(i: Item, f: Filters, kids: Kids, skipFolder = false): boolean {
  if (f.letter !== "All" && firstLetter(i, kids) !== f.letter) return false;
  if (!skipFolder && f.group && f.folder != null && !folderOf(i, f.group, kids).includes(f.folder)) return false;
  if (f.q && !qMatch(i, f.q) && !(i.is_set && kids(i).some((k) => qMatch(k, f.q)))) return false;
  return true;
}

/** The films in a set that brought it into a search or folder, when that's
 *  only some of them. */
export function hits(i: Item, f: Filters, kids: Kids): Item[] {
  if (!i.is_set || (!f.q && f.folder == null)) return [];
  // Found by its own name: the whole set's the answer.
  if (f.q && f.folder == null && qMatch(i, f.q)) return [];
  const k = kids(i);
  const h = k.filter((x) => qMatch(x, f.q) && (!f.group || f.folder == null || folderValues(x, f.group).includes(f.folder)));
  return h.length < k.length ? h : [];
}
