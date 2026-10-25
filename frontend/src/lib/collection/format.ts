// Small helpers the collection page builds its HTML with.
import badges from "../badges.json";
import { ageRating } from "./shelf";

export const esc = (v: unknown) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

/** "2026-10-25" -> "25 Oct 2026". */
export const fmtDate = (s?: string | null) =>
  s ? new Date(`${s.slice(0, 10)}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "";

export const list2 = (v?: string[]) => (v?.length ? v.join(", ") : "");
export const money = (v?: number | null) => (v != null ? v.toFixed(2) : "");

// The user's Collectorz icons for formats, regions and age ratings; empty
// where there's none, so callers fall back to a text badge.
const badgeImg = (src: string | undefined, label: string, cls: string) =>
  src ? `<img class="${cls}" src="${src}" alt="${esc(label)}" title="${esc(label)}" />` : "";
export const formatIcon = (f?: string, cls = "cd-icon") =>
  badgeImg(f ? (badges.format as Record<string, string>)[f] : undefined, f || "", cls);
export const regionIcon = (r: string, cls = "cd-icon") =>
  badgeImg((badges.region as Record<string, string>)[r], r, cls);
export const ratingIcon = (r?: string, cls = "cd-icon") =>
  badgeImg(r ? (badges.rating as Record<string, string>)[r.replace(/[^A-Za-z0-9]/g, "").toUpperCase()] : undefined, ageRating(r), cls);
