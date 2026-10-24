"""Check the nominee names on award lists against the title's own credits and
Wikidata, to catch a name that is wrong but looks right.

    python scripts/check_award_names.py movie 872585 238 597
    python scripts/check_award_names.py show 2734 1396

For each named nomination it checks that:
  - an acting nominee is in the cast, and of the category's gender;
  - a worked-out crew nominee (director, editor…) holds that job in the
    credits (names on record are left alone: credits word jobs loosely);
  - Wikidata, where it names someone for that award and year, agrees.
It also lists every name that was worked out rather than on record, so those
can be eyeballed. Uses the first user's TVDB and TMDB keys.
"""
from pathlib import Path
import asyncio
import re
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))

from db import AsyncSessionLocal
from core import awards, tmdb, tvdb, wikidata
from routers.media import get_user_tmdb_key
from routers.shows import TV_FAMILIES, _name_award_nominees, get_user_tvdb_key


_people = awards.split_names


def _norm(name: str) -> str:
    return awards.norm_title(name)


async def _title(kind: str, tmdb_id: int, tvdb_key: str, tmdb_key: str | None):
    """(title, awards, cast {name: gender}, crew {name: jobs}, Wikidata rows),
    with Wikidata names taken from the credits by TMDB id where possible."""
    if kind == "movie":
        movie = await tmdb.get_movie(tmdb_id, api_key=tmdb_key)
        rows = await awards.film_awards(tmdb_id, tvdb_key, tmdb_key, movie)
        credits = movie.get("credits") or {}
        cast = {_norm(c["name"]): c.get("gender") for c in credits.get("cast") or []}
        crew: dict[str, set] = {}
        for c in credits.get("crew") or []:
            crew.setdefault(_norm(c["name"]), set()).add(c.get("job"))
        ids = {c["id"]: c["name"] for c in [*(credits.get("cast") or []), *(credits.get("crew") or [])]}
        return movie.get("title"), rows, cast, crew, _named(await wikidata.film_award_people(tmdb_id), ids)

    show = await tmdb.get_show(tmdb_id, api_key=tmdb_key)
    tvdb_id = (show.get("external_ids") or {}).get("tvdb_id")
    if not tvdb_id:
        return show.get("name"), [], {}, {}, []
    rows = [a for a in await tvdb.get_series_awards(tvdb_id, tvdb_key) if awards.family(a["award_name"]) in TV_FAMILIES]
    rows = await _name_award_nominees(rows, tmdb_id, tmdb_key)
    agg = show.get("aggregate_credits") or {}
    cast = {_norm(c["name"]): c.get("gender") for c in agg.get("cast") or []}
    crew: dict[str, set] = {}  # one entry per person and department
    for c in agg.get("crew") or []:
        crew.setdefault(_norm(c["name"]), set()).update(j.get("job") for j in c.get("jobs") or [])
    ids = {c["id"]: c["name"] for c in [*(agg.get("cast") or []), *(agg.get("crew") or [])]}
    return show.get("name"), rows, cast, crew, _named(await wikidata.tv_award_people(tmdb_id), ids)


def _named(wd_rows: list[dict], ids: dict[int, str]) -> list[dict]:
    """Wikidata rows with English names: from the credits by TMDB id, as some
    people have no English label (just a Q-number)."""
    out = []
    for w in wd_rows:
        name = ids.get(w.get("person_tmdb_id")) or w.get("person_name")
        out.append({**w, "person_name": None if name and re.fullmatch(r"Q\d+", name) else name})
    return out


def _check(rows, cast, crew, wd_rows) -> tuple[list[str], list[str], int]:
    problems, inferred, named = [], [], 0
    for r in rows:
        people = _people(r.get("person_name"))
        if not people:
            continue
        named += 1
        label = f'{r["year"]} {r["award_name"]} | {r["category_name"]} – {r["person_name"]}'
        if r.get("name_inferred"):
            inferred.append(label)
        cat = r["category_name"]
        kind = awards.role_kind(cat)
        for p in people:
            n = _norm(p)
            if kind == "acting":
                if n not in cast:
                    problems.append(f"{label}\n      {p} isn't in the cast")
                elif awards._gender(cat) and cast[n] not in (0, None, awards._gender(cat)):
                    problems.append(f"{label}\n      {p}'s gender doesn't fit the category")
            elif r.get("name_inferred") and awards.topic_jobs(cat) and crew:
                primary, fallback = awards.topic_jobs(cat)
                if n in crew and not crew[n] & (primary | fallback):
                    problems.append(f"{label}\n      {p} is credited as {', '.join(sorted(j for j in crew[n] if j))}, not this job")
        # Wikidata naming someone else for the same award, year and category.
        year = awards._year(r["year"])
        for w in wd_rows:
            if awards.family(w["award_name"]) != awards.family(r["award_name"]) or not w.get("person_name"):
                continue
            if not year or not awards._year(w["year"]) or abs(awards._year(w["year"]) - year) > 1:
                continue
            if awards.topic(w["category_name"]) != awards.topic(cat) or w["is_winner"] != r["is_winner"]:
                continue
            if kind == "acting" and _norm(w["person_name"]) not in {_norm(p) for p in people}:
                # Only a disagreement if no other row of ours carries that name.
                elsewhere = any(
                    _norm(w["person_name"]) in {_norm(p) for p in _people(o.get("person_name"))}
                    and awards.topic(o["category_name"]) == awards.topic(cat)
                    and awards.family(o["award_name"]) == awards.family(r["award_name"])
                    for o in rows
                )
                if not elsewhere:
                    problems.append(f"{label}\n      Wikidata has {w['person_name']} for {w['award_label']} ({w['year']})")
    return problems, inferred, named


async def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("movie", "show"):
        print(__doc__)
        return
    async with AsyncSessionLocal() as db:
        tvdb_key, tmdb_key = await get_user_tvdb_key(db, 1), await get_user_tmdb_key(db, 1)
    total_problems = 0
    for tmdb_id in map(int, sys.argv[2:]):
        title, rows, cast, crew, wd_rows = await _title(sys.argv[1], tmdb_id, tvdb_key, tmdb_key)
        problems, inferred, named = _check(rows, cast, crew, wd_rows)
        total_problems += len(problems)
        print(f"\n== {title} ({tmdb_id}): {len(rows)} nominations, {named} named, {len(inferred)} worked out, {len(problems)} to look at")
        for p in problems:
            print("  ! " + p)
        for i in inferred:
            print("  ~ " + i)
    print(f"\n{total_problems} to look at in total.")


if __name__ == "__main__":
    asyncio.run(main())
