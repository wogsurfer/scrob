// Every column the collection's list view can show (the ones Collectorz has,
// plus Watchd's own), in groups for the chooser. `sort` is the value a column
// sorts by where it isn't the field itself; `cell` what it shows.
import type { PhysicalSummary } from "../api";
import { esc, fmtDate, formatIcon, list2, money, ratingIcon, regionIcon } from "./format";
import { ageRating, formatClass, formatLabel } from "./shelf";

type Item = PhysicalSummary;
export type Col = { label: string; group: string; sort?: (i: Item) => unknown; cell?: (i: Item) => string; dim?: boolean };

export const DEFAULT_COLS = ["title", "release_year", "format", "edition", "distributor", "purchase_date", "store", "my_rating", "seen"];

/** The columns; `setTitle` names the box set an entry is (or is in). */
export function makeColumns(setTitle: (i: Item) => string): Record<string, Col> {
  return {
    title: { label: "Title", group: "Film" },
    original_title: { label: "Original title", group: "Film", dim: true },
    release_year: { label: "Year", group: "Film" },
    director: { label: "Director", group: "Film", dim: true },
    writer: { label: "Writer", group: "Film", dim: true },
    producer: { label: "Producer", group: "Film", dim: true },
    composer: { label: "Composer", group: "Film", dim: true },
    cinematography: { label: "Cinematography", group: "Film", dim: true },
    actors: { label: "Cast", group: "Film", dim: true, sort: (i) => list2(i.actors), cell: (i) => esc(list2(i.actors)) },
    genres: { label: "Genre", group: "Film", dim: true, sort: (i) => list2(i.genres), cell: (i) => esc(list2(i.genres)) },
    studios: { label: "Studio", group: "Film", dim: true, sort: (i) => list2(i.studios), cell: (i) => esc(list2(i.studios)) },
    country: { label: "Country", group: "Film", dim: true },
    language: { label: "Language", group: "Film", dim: true },
    runtime: { label: "Running time", group: "Film", cell: (i) => (i.runtime ? `${i.runtime} min` : "") },
    audience_rating: { label: "Age rating", group: "Film", cell: (i) => ratingIcon(i.audience_rating, "coll-icon") || esc(ageRating(i.audience_rating)) },
    imdb_rating: { label: "IMDb rating", group: "Film" },
    imdb_votes: { label: "IMDb votes", group: "Film", cell: (i) => (i.imdb_votes ? i.imdb_votes.toLocaleString() : "") },
    adaptation_of: { label: "Adaptation of", group: "Film", dim: true },
    series: { label: "Series", group: "Film", dim: true },
    franchise: { label: "Franchise", group: "Film", dim: true },
    kind: { label: "Film or TV", group: "Film", sort: (i) => (i.is_tv ? "TV" : "Film"), cell: (i) => (i.is_tv ? "TV" : "Film") },
    format: { label: "Format", group: "Edition", cell: (i) => (i.format ? formatIcon(i.format, "coll-icon") || `<span class="coll-fmt-inline coll-fmt-${formatClass(i.format)}">${esc(formatLabel(i.format))}</span>` : "") },
    edition: { label: "Edition", group: "Edition", dim: true },
    distributor: { label: "Distributor", group: "Edition", dim: true },
    barcode: { label: "Barcode", group: "Edition", dim: true },
    package: { label: "Packaging", group: "Edition", dim: true },
    disc_count: { label: "Discs", group: "Edition" },
    disc_release_date: { label: "Disc release", group: "Edition", cell: (i) => esc(fmtDate(i.disc_release_date)) },
    regions: { label: "Region", group: "Edition", sort: (i) => list2(i.regions), cell: (i) => (i.regions || []).map((r) => regionIcon(r, "coll-icon") || esc(r.replace("Region ", ""))).join(" ") },
    ratios: { label: "Aspect ratio", group: "Edition", dim: true, sort: (i) => list2(i.ratios), cell: (i) => esc(list2(i.ratios)) },
    audio: { label: "Audio", group: "Edition", dim: true, sort: (i) => list2(i.audio), cell: (i) => esc(list2(i.audio)) },
    subtitles: { label: "Subtitles", group: "Edition", dim: true, sort: (i) => list2(i.subtitles), cell: (i) => esc(list2(i.subtitles)) },
    layers: { label: "Layers", group: "Edition", dim: true },
    hdr: { label: "HDR", group: "Edition", dim: true },
    color: { label: "Colour", group: "Edition", dim: true },
    extras: { label: "In the box", group: "Edition", dim: true, sort: (i) => list2(i.extras), cell: (i) => esc(list2(i.extras)) },
    in_set: { label: "Box set", group: "Edition", dim: true, sort: setTitle, cell: (i) => esc(setTitle(i)) },
    status: { label: "Collection status", group: "Personal", cell: (i) => (i.status === "wishlist" ? "Wish list" : i.status === "owned" ? "In collection" : esc(i.status)) },
    purchase_date: { label: "Purchased", group: "Personal", cell: (i) => esc(fmtDate(i.purchase_date)) },
    purchase_price: { label: "Price", group: "Personal", cell: (i) => money(i.purchase_price) },
    current_value: { label: "Value", group: "Personal", cell: (i) => money(i.current_value) },
    store: { label: "Store", group: "Personal", dim: true },
    condition: { label: "Condition", group: "Personal", dim: true },
    location: { label: "Location", group: "Personal", dim: true },
    owner: { label: "Owner", group: "Personal", dim: true },
    index_no: { label: "Index", group: "Personal" },
    my_rating: { label: "My rating", group: "Personal", cell: (i) => (i.my_rating ? `${i.my_rating}/10` : "") },
    seen: { label: "Seen", group: "Personal", sort: (i) => (i.seen ? 1 : 0), cell: (i) => (i.seen ? "Yes" : "") },
    plays: { label: "Plays", group: "Personal", cell: (i) => (i.plays ? String(i.plays) : "") },
    viewing_date: { label: "Viewing date", group: "Personal", cell: (i) => esc(fmtDate(i.viewing_date)) },
    seen_in_cinema: { label: "Seen in cinema", group: "Personal", dim: true },
    tags: { label: "Tags", group: "Personal", dim: true, sort: (i) => list2(i.tags), cell: (i) => esc((i.tags || []).map((t) => `#${t}`).join(" ")) },
    notes: { label: "Notes", group: "Personal", dim: true },
    date_added: { label: "Added", group: "Personal", cell: (i) => esc(fmtDate(i.date_added)) },
    updated_at: { label: "Modified", group: "Personal", cell: (i) => esc(fmtDate(i.updated_at)) },
  };
}
