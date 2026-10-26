import { describe, expect, it } from "vitest";
import type { PhysicalSummary } from "../api";
import {
  ageRating, firstLetter, folderOf, hits, matches, prepareSets, setSize, sortItems, type Filters,
} from "./shelf";

let nextId = 1;
const disc = (title: string, extra: Partial<PhysicalSummary> = {}): PhysicalSummary =>
  ({ id: nextId++, status: "owned", title, ...extra }) as PhysicalSummary;
const titles = (items: PhysicalSummary[]) => items.map((i) => i.title);
const noFilters: Filters = { q: "", letter: "All", group: "", folder: null };

describe("shelf order", () => {
  it("files like the shelf: punctuation first, then numbers in order, articles ignored", () => {
    const items = [
      disc("Absolute Power"), disc("300"), disc("The 'Burbs"), disc("¡Three Amigos!"), disc("12 Angry Men"),
      disc("(500) Days of Summer"), disc("2 Guns"), disc("The Abyss"), disc("3:10 to Yuma"), disc("3 Days of the Condor"),
    ];
    const kids = prepareSets(items);
    expect(titles(sortItems(items, "title", 1, kids))).toEqual([
      "The 'Burbs", "(500) Days of Summer", "2 Guns", "3 Days of the Condor", "3:10 to Yuma", "12 Angry Men", "300",
      "Absolute Power", "The Abyss", "¡Three Amigos!",
    ]);
  });

  it("reads & as and, and uses the sort title", () => {
    // As "fast and furious", it comes after "fast afternoon"; a bare "&"
    // would sort before every letter.
    const items = [disc("Fast & Furious"), disc("Fast Afternoon"), disc("Fast Five", { sort_title: "The Fast and the Furious 05" })];
    const kids = prepareSets(items);
    expect(titles(sortItems(items, "title", 1, kids))).toEqual(["Fast Afternoon", "Fast & Furious", "Fast Five"]);
  });

  it("puts each title in its letter pile", () => {
    const kids = prepareSets([]);
    expect(firstLetter(disc("The 'Burbs"), kids)).toBe("#");
    expect(firstLetter(disc("300"), kids)).toBe("#");
    expect(firstLetter(disc("¡Three Amigos!"), kids)).toBe("T");
    expect(firstLetter(disc("The Abyss"), kids)).toBe("A");
  });

  it("files a box set by its first film unless it has its own sort title", () => {
    const set = disc("The Ultimate Bourne Collection", { is_set: true });
    const own = disc("Peanuts Deluxe Holiday Collection", { is_set: true, own_sort: true, sort_title: "Peanuts" });
    const items = [
      set, disc("The Bourne Supremacy", { parent_id: set.id, position: 2 }), disc("The Bourne Identity", { parent_id: set.id, position: 1 }),
      own, disc("A Charlie Brown Christmas", { parent_id: own.id, position: 1 }), disc("Casino"), disc("Oblivion"),
    ];
    const kids = prepareSets(items);
    const shelf = items.filter((i) => !i.parent_id);
    expect(titles(sortItems(shelf, "title", 1, kids))).toEqual(["The Ultimate Bourne Collection", "Casino", "Oblivion", "Peanuts Deluxe Holiday Collection"]);
    expect(firstLetter(set, kids)).toBe("B");
  });

  it("puts blanks first going up and last going down", () => {
    const items = [disc("A", { purchase_date: "2020-01-01" }), disc("B"), disc("C", { purchase_date: "2024-05-01" })];
    const kids = prepareSets(items);
    expect(titles(sortItems(items, "purchase_date", 1, kids))).toEqual(["B", "A", "C"]);
    expect(titles(sortItems(items, "purchase_date", -1, kids))).toEqual(["C", "A", "B"]);
  });
});

describe("box sets", () => {
  it("counts a set as seen only when all its films are, and takes its earliest year", () => {
    const set = disc("Trilogy", { is_set: true });
    const items = [set, disc("One", { parent_id: set.id, seen: true, release_year: 1985 }), disc("Two", { parent_id: set.id, seen: false, release_year: 1989 })];
    prepareSets(items);
    expect(set.seen).toBe(false);
    expect(set.release_year).toBe(1985);
  });

  it("names the size of a set", () => {
    expect(setSize([disc("a"), disc("b")])).toBe("2 films");
    expect(setSize([disc("a", { is_tv: true })])).toBe("1 season");
    expect(setSize([disc("a", { is_tv: true }), disc("b")])).toBe("2 titles");
  });

  it("finds a set through its films, and says which films matched", () => {
    const set = disc("Double Feature - Chevy Chase", { is_set: true });
    const spies = disc("Spies Like Us", { parent_id: set.id, director: "John Landis" });
    const items = [set, spies, disc("Funny Farm", { parent_id: set.id, director: "George Roy Hill" })];
    const kids = prepareSets(items);
    const f = { ...noFilters, q: "spies" };
    expect(matches(set, f, kids)).toBe(true);
    expect(hits(set, f, kids)).toEqual([spies]);
    // Found by its own name: no single films picked out.
    expect(hits(set, { ...noFilters, q: "chevy" }, kids)).toEqual([]);
  });

  it("keeps a set of seasons and films whole under TV and Film", () => {
    const set = disc("Batman: The Complete Animated Series", { is_set: true });
    const items = [set, disc("Season 1", { parent_id: set.id, is_tv: true }), disc("Mask of the Phantasm", { parent_id: set.id })];
    const kids = prepareSets(items);
    const f = { ...noFilters, group: "kind", folder: "TV" };
    expect(matches(set, f, kids)).toBe(true);
    expect(hits(set, f, kids)).toEqual([]);
  });

  it("puts a set in every folder its films are in", () => {
    const set = disc("Double Feature", { is_set: true, format: "Blu-ray" });
    const items = [set, disc("One", { parent_id: set.id, director: "John Landis" }), disc("Two", { parent_id: set.id, director: "George Roy Hill" })];
    const kids = prepareSets(items);
    expect(folderOf(set, "director", kids).sort()).toEqual(["George Roy Hill", "John Landis"]);
    expect(folderOf(set, "format", kids)).toEqual(["Blu-ray"]);
  });
});

describe("labels", () => {
  it("shortens age ratings", () => {
    expect(ageRating("MPAAPG-13")).toBe("PG-13");
    expect(ageRating("BBFC15")).toBe("BBFC 15");
    expect(ageRating(undefined)).toBe("");
  });
});
