"""Film and person awards: Oscars, Golden Globes and BAFTAs for films, plus
Golden Globes and Emmys for TV.

TVDB has the complete nomination lists but names only the film, so the
nominee is worked out per category: whoever Wikidata names, or failing that
the film's credited crew for the category (director, writers, editor…) or for
acting the top-billed cast member of the right gender. A person's awards are
then the ones attributed to them across their films and shows, plus anything
else Wikidata lists for them.
"""
import asyncio
import re
import time
import unicodedata

from core import disk_cache, tmdb, tvdb, wikidata

_TTL = 24 * 3600
_film_cache: dict[int, tuple[float, list[dict]]] = {}
_person_cache: dict[int, tuple[float, list[dict]]] = {}
_film_titles: tuple[int, dict[str, list[tuple[dict, dict, dict]]]] | None = None
_series_titles: tuple[int, dict[str, list[tuple[dict, dict, dict]]]] | None = None

# TMDB crew jobs credited for each category topic (see topic()): the primary
# jobs, then a fallback when no one holds those. Screenwriters come before
# the story credit.
_TOPIC_JOBS = {
    "director": ({"Director"}, set()),
    "cinematography": ({"Director of Photography", "Cinematography"}, set()),
    "screenplay": ({"Screenplay", "Writer", "Teleplay"}, {"Story"}),
    "editing": ({"Editor"}, set()),
    "score": ({"Original Music Composer", "Music", "Composer"}, set()),
    "song": ({"Songs", "Original Song"}, set()),
    "design": ({"Production Design", "Set Decoration"}, {"Art Direction"}),
    "costume": ({"Costume Design", "Costume Designer"}, set()),
    "makeup": ({"Makeup Department Head", "Hair Department Head", "Makeup Designer", "Prosthetic Designer"}, set()),
    "sound": ({"Sound Re-Recording Mixer", "Supervising Sound Editor", "Production Sound Mixer"}, {"Sound Designer"}),
    "vfx": ({"Visual Effects Supervisor"}, set()),
    "casting": ({"Casting"}, set()),
    "picture": ({"Producer"}, set()),
    "british": ({"Producer"}, set()),
    "animated": ({"Director"}, set()),
    "documentary": ({"Director"}, set()),
}
# More credited people than this for one category means the credits list a
# whole department, not the nominees; better no names than a wall of them.
_MAX_CREDITED = 5
TV_FAMILIES = ("globe", "emmy")


def topic_jobs(category: str) -> tuple[set[str], set[str]] | None:
    return _TOPIC_JOBS.get(topic(category).split("-")[0])


def credited(crew: list[dict], category: str) -> list[dict]:
    """The crew credited with the job a category honours, e.g. the editor."""
    jobs = topic_jobs(category)
    for wanted in jobs or ():
        people = list({c["id"]: {"id": c["id"], "name": c["name"]} for c in crew if c.get("job") in wanted}.values())
        if people:
            return people if len(people) <= _MAX_CREDITED else []
    return []


def role_kind(category: str) -> str | None:
    c = (category or "").lower()
    if re.search(r"actress|actor|performance", c):
        return "acting"
    if "cinematograph" in c:
        return "cinematography"
    if re.search(r"screenplay|writ", c):
        return "writing"
    if "direct" in c and not re.search(r"art direction|set direction|production design", c):
        return "directing"
    return None


def _gender(category: str) -> int | None:
    """TMDB gender for an acting category: 1 actress, 2 actor, None either."""
    c = (category or "").lower()
    return 1 if "actress" in c else 2 if "actor" in c else None


def _genre(category: str) -> str | None:
    c = (category or "").lower()
    return "comedy" if re.search(r"comedy|musical", c) else "drama" if "drama" in c else None


def family(award_name: str) -> str | None:
    a = (award_name or "").lower()
    return ("oscar" if "academy award" in a else "globe" if "golden globe" in a
            else "bafta" if "bafta" in a or "british academy" in a else "emmy" if "emmy" in a else None)


def norm_title(title: str | None) -> str:
    t = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    return re.sub(r"^(the|a|an) ", "", t)


def _year(value) -> int | None:
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None


def topic(category: str) -> str:
    """What a category is for, comparable across award bodies' wording:
    "Actress in a Supporting Role" and "Best Supporting Actress" are both
    "actress-supporting"."""
    c = (category or "").lower()
    if role_kind(c) == "acting":
        who = "actress" if "actress" in c else "actor" if "actor" in c else "performer"
        return f"{who}-{'guest' if 'guest' in c else 'supporting' if 'support' in c else 'lead'}"
    for pattern, name in (
        (r"cinematograph", "cinematography"),
        (r"adapted", "screenplay-adapted"),
        (r"original screenplay|screenplay.*original|original.*screenplay", "screenplay-original"),
        (r"screenplay|writ", "screenplay"),
        (r"art direction|production design|set decoration", "design"),
        (r"direct", "director"),
        # Before editing: "Sound Effects Editing" is a sound award.
        (r"sound (effects )?editing", "sound-editing"),
        (r"sound", "sound"),
        (r"editing", "editing"),
        (r"song", "song"),
        (r"score|original music|music \(original|music composition", "score"),
        (r"costume", "costume"),
        (r"make-?up", "makeup"),
        (r"visual effects|special effects", "vfx"),
        (r"animat", "animated"),
        (r"documentary", "documentary"),
        (r"foreign|international|not in the english language|non-english", "international"),
        (r"casting", "casting"),
        (r"british film|british debut", "british"),
        (r"picture|film", "picture"),
    ):
        if re.search(pattern, c):
            return name
    return c


def join_names(names: list[str]) -> str | None:
    """"A", "A & B", "A, B & C"."""
    names = [n for n in names if n]
    return ", ".join(names[:-1]) + " & " + names[-1] if len(names) > 1 else names[0] if names else None


def split_names(person_name: str | None) -> list[str]:
    """The names in a person_name built by join_names."""
    return [n.strip() for n in re.split(r" & |, ", person_name or "") if n.strip()]


def _close_years(a, b) -> bool:
    a, b = _year(a), _year(b)
    return not a or not b or abs(a - b) <= 1


def _same_topic(a: str, b: str) -> bool:
    # A plain "Best Screenplay" (Golden Globes) covers original and adapted.
    return a == b or {a.split("-")[0], b.split("-")[0]} == {"screenplay"} and "screenplay" in (a, b)


def _wikidata_groups(wd_rows: list[dict], names: dict[int, str], families=("oscar", "globe", "bafta")) -> list[dict]:
    """Wikidata rows as nominations: acting is one per person; elsewhere the
    people sharing a nomination (a film's producers, its sound team) are one."""
    groups: dict[tuple, dict] = {}
    for r in wd_rows:
        if family(r["award_name"]) not in families:
            continue
        person_id = r.get("person_tmdb_id")
        name = names.get(person_id) or r.get("person_name")
        if name and re.fullmatch(r"Q\d+", name):
            name = None  # no English label on Wikidata
        acting = role_kind(r["category_name"]) == "acting"
        key = (r["award_label"], r["year"], r["is_winner"], person_id if acting else None)
        group = groups.setdefault(key, {**r, "people": []})
        if (person_id or name) and all(p["id"] != person_id or p["name"] != name for p in group["people"]):
            group["people"].append({"id": person_id, "name": name})
    # The same nomination is sometimes recorded twice, dated a year apart
    # (the year of the film and the year of the ceremony).
    out: list[dict] = []
    for g in groups.values():
        people = {(p["id"], p["name"]) for p in g["people"]}
        if not any(
            o["award_label"] == g["award_label"] and o["is_winner"] == g["is_winner"] and people
            and {(p["id"], p["name"]) for p in o["people"]} == people and _close_years(o["year"], g["year"])
            for o in out
        ):
            out.append(g)
    return out


def name_tv_awards(awards: list[dict], wd_rows: list[dict]) -> list[dict]:
    """Fill in a show's unnamed nominees from Wikidata, and add the Golden
    Globe and Emmy nominations Wikidata has that TVDB doesn't."""
    groups = _wikidata_groups(wd_rows, {}, TV_FAMILIES)
    # The show's own nomination in a category carries no person; drop it when
    # the person's own record for that award and year is there.
    with_people = {(g["award_label"], g["year"]) for g in groups if g["people"]}
    groups = [g for g in groups if g["people"] or (g["award_label"], g["year"]) not in with_people]
    used: set[int] = set()

    def match(award: dict) -> dict | None:
        cat, year = award.get("category_name") or "", _year(award.get("year"))
        for i, g in enumerate(groups):
            if i in used or family(g["award_name"]) != family(award.get("award_name")):
                continue
            if year and g["year"] and abs(_year(g["year"]) - year) > 1:
                continue
            if not _same_topic(topic(g["category_name"]), topic(cat)):
                continue
            if _genre(g["category_name"]) and _genre(cat) and _genre(g["category_name"]) != _genre(cat):
                continue
            used.add(i)
            return g
        return None

    def joined(people: list[dict]) -> str | None:
        return join_names([p.get("name") for p in people])

    named = []
    shared = set()  # see _name_film_awards
    # Already-named nominations first, so they claim their Wikidata twin and
    # it isn't added again as a separate row.
    for award in sorted(awards, key=lambda a: not a.get("person_name")):
        group = match(award)
        if group and not award.get("person_name") and joined(group["people"]):
            award = {**award, "person_name": joined(group["people"])}
            if len(group["people"]) > 1 and role_kind(award.get("category_name")) != "acting":
                shared.add(_key(award))
        elif not group and not award.get("person_name") and _key(award) in shared:
            continue
        named.append(award)
    for i, g in enumerate(groups):
        if i not in used:
            named.append({
                "award_id": None,
                "award_name": g["award_name"],
                "category_id": None,
                "category_name": g["category_name"],
                "year": g["year"],
                "is_winner": g["is_winner"],
                "details": None,
                "person_name": joined(g["people"]),
            })

    # Acting nominations still unnamed and with no character given: the one
    # person the show's other nominations that year name in a like role
    # (lead, or supporting/guest) of the same gender, if there is exactly one.
    def role(category: str) -> tuple | None:
        t = topic(category)
        if role_kind(category) != "acting":
            return None
        return _gender(category), t.endswith("-lead") and "guest" not in (category or "").lower()

    for i, award in enumerate(named):
        # A nomination naming a character belongs to whoever played it; if
        # that didn't match, it is someone else, not a fellow nominee.
        if award.get("person_name") or not role(award["category_name"]) or _PLAYED.search(award.get("details") or ""):
            continue
        year = _year(award["year"])
        people = {
            other["person_name"] for other in named
            if other.get("person_name") and role(other["category_name"]) == role(award["category_name"])
            and year and _year(other["year"]) and abs(_year(other["year"]) - year) <= 1
        }
        if len(people) == 1:
            named[i] = {**award, "person_name": people.pop(), "name_inferred": True}
    return _dedupe(named, "person_name")


def _name_film_awards(awards: list[dict], credits: dict, wd_rows: list[dict]) -> list[dict]:
    cast = sorted(credits.get("cast") or [], key=lambda c: c.get("order", 999))
    crew = credits.get("crew") or []
    names = {c["id"]: c["name"] for c in [*cast, *crew] if c.get("id") and c.get("name")}
    groups = _wikidata_groups(wd_rows, names)
    # The film's own record of a nomination, with no one named, often sits
    # beside the nominee's record of the same one; keep just the named one.
    groups = [g for g in groups if g["people"] or not any(
        h["people"] and family(h["award_name"]) == family(g["award_name"])
        and _same_topic(topic(h["category_name"]), topic(g["category_name"]))
        and _close_years(h["year"], g["year"])
        for h in groups
    )]
    used: set[int] = set()
    # Acting nominees already named per (award, year), so a film's lead and
    # supporting nominations don't both land on its top-billed star.
    named_acting: dict[tuple[str, str], set[int]] = {}

    def wikidata_match(award: dict) -> list[dict]:
        cat, year = award["category_name"], _year(award["year"])
        for i, g in enumerate(groups):
            if i in used or family(g["award_name"]) != family(award["award_name"]):
                continue
            if year and g["year"] and abs(_year(g["year"]) - year) > 1:
                continue
            if not _same_topic(topic(g["category_name"]), topic(cat)):
                continue
            if _genre(g["category_name"]) and _genre(cat) and _genre(g["category_name"]) != _genre(cat):
                continue
            used.add(i)
            return g["people"]
        return []

    def billing_guess(award: dict) -> list[dict]:
        gender = _gender(award["category_name"])
        own = topic(award["category_name"])
        # Someone this award body nominated in another acting category isn't
        # this one. Other bodies don't count: they place people differently
        # (Uma Thurman was a supporting actress to the Oscars, a lead to BAFTA).
        elsewhere = {p["id"] for (fam, t), people in known.items()
                     if fam == family(award["award_name"]) and t != own for p in people}
        pool = [c for c in cast if (gender is None or c.get("gender") in (gender, 0)) and c.get("id") not in elsewhere]
        taken = named_acting.get((award["award_name"], str(award["year"])), set())
        if "support" in award["category_name"].lower() and pool:
            pool = pool[1:]  # the top-billed one is taken to be the lead
        pick = next((c for c in pool if c.get("id") not in taken), None)
        return [{"id": pick["id"], "name": pick["name"]}] if pick else []

    def joined(people: list[dict]) -> str | None:
        return join_names([p.get("name") for p in people])

    # Wikidata first (it records the actual nominees). Then, for acting, the
    # person another award body named in the same category (an Oscar nominee
    # for Best Supporting Actress is the film's Golden Globe nominee too),
    # then a guess from the billing; for crew, the film's credited crew.
    rows = list(awards)
    found = [wikidata_match(a) for a in rows]
    # Nominations Wikidata has and TVDB doesn't (TVDB misses some Best
    # Picture years) are named the same way.
    for i, g in enumerate(groups):
        if i not in used:
            rows.append({
                "award_id": None,
                "award_name": g["award_name"],
                "category_id": None,
                "category_name": g["category_name"],
                "year": g["year"],
                "is_winner": g["is_winner"],
                "details": None,
                "person_name": None,
            })
            found.append(g["people"])

    by_topic: dict[str, list[dict]] = {}
    known: dict[tuple[str, str], list[dict]] = {}
    for award, people in zip(rows, found):
        if people and role_kind(award["category_name"]) == "acting":
            by_topic.setdefault(topic(award["category_name"]), people)
            known.setdefault((family(award["award_name"]), topic(award["category_name"])), []).extend(people)
            named_acting.setdefault((award["award_name"], str(award["year"])), set()).update(p["id"] for p in people)

    # TVDB lists a shared nomination (two writers, three producers) once per
    # nominee; once Wikidata has named the whole team on one row, the
    # other copies are dropped rather than given a guessed name.
    shared = {_key(a) for a, people in zip(rows, found) if len(people) > 1 and role_kind(a["category_name"]) != "acting"}

    named = []
    for award, people in zip(rows, found):
        kind = role_kind(award["category_name"])
        if not people and _key(award) in shared:
            continue
        # Names from the billing or the crew list are guesses, not records.
        inferred = False
        if not people and kind == "acting":
            taken = named_acting.setdefault((award["award_name"], str(award["year"])), set())
            people = by_topic.get(topic(award["category_name"])) or []
            # Two nominations in one category (Brando and Pacino) are two people.
            if not people or any(p["id"] in taken for p in people):
                people = billing_guess(award)
                inferred = bool(people)
            taken.update(p["id"] for p in people)
        elif not people:
            people = credited(crew, award["category_name"])
            inferred = bool(people)
        named.append({
            **award,
            "person_name": joined(people) or award.get("person_name"),
            "person_ids": [p["id"] for p in people if p.get("id")],
            "name_inferred": inferred,
        })
    return _dedupe(named, "person_name")


def _key(award: dict) -> tuple:
    # Details tell apart separate nominations in one category (two episodes).
    return award["award_name"], award["category_name"], str(award["year"]), award["is_winner"], award.get("details") or ""


def _dedupe(rows: list[dict], subject: str) -> list[dict]:
    """TVDB sometimes lists the same nomination twice."""
    seen, out = set(), []
    for r in rows:
        key = (r["award_name"], r["category_name"], str(r["year"]), r["is_winner"], r.get(subject))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


async def film_awards(movie_tmdb_id: int, tvdb_key: str, tmdb_key: str | None, movie: dict | None = None) -> list[dict]:
    """A film's Oscar, Golden Globe and BAFTA nominations, with nominees named."""
    hit = _film_cache.get(movie_tmdb_id) or disk_cache.load("film_awards", movie_tmdb_id, _TTL)
    if hit and time.time() - hit[0] < _TTL:
        _film_cache[movie_tmdb_id] = hit
        return hit[1]

    if movie is None:
        movie = await tmdb.get_movie(movie_tmdb_id, api_key=tmdb_key)
    imdb_id = (movie.get("external_ids") or {}).get("imdb_id") or movie.get("imdb_id")
    tvdb_id = await tvdb.find_movie_by_imdb(imdb_id, tvdb_key) if imdb_id else None
    if tvdb_id:
        # Categories covering both films and series (MTV, SAG…) bring other
        # awards along; film pages keep to the three film awards.
        awards = [a for a in await tvdb.get_movie_awards(tvdb_id, tvdb_key) if a["award_name"] in tvdb.FILM_AWARDS]
    else:
        # No IMDb link on TVDB: fall back to the film's title and year.
        year = _year(movie.get("release_date"))
        titles = await _film_title_index(tvdb_key)
        awards = [
            tvdb.award_entry(a, c, n)
            for t in {norm_title(movie.get("title")), norm_title(movie.get("original_title"))} if t
            for a, c, n in titles.get(t, [])
            if year and _year((n.get("movie") or {}).get("year")) in (year - 1, year, year + 1)
        ]

    wd_rows = await wikidata.film_award_people(movie_tmdb_id)
    named = _name_film_awards(awards, movie.get("credits") or {}, wd_rows)
    _film_cache[movie_tmdb_id] = (time.time(), named)
    disk_cache.save("film_awards", movie_tmdb_id, named)
    return named


def _title_keys(title: dict | None) -> set[str]:
    if not title:
        return set()
    # Aliases are plain names in the slimmed index, {language, name} in an older one.
    aliases = [a.get("name") if isinstance(a, dict) else a for a in title.get("aliases") or []]
    return {k for k in (norm_title(n) for n in [title.get("name"), *aliases]) if k}


async def _film_title_index(tvdb_key: str) -> dict[str, list[tuple[dict, dict, dict]]]:
    """Film nominees of the major film awards, keyed by normalised title."""
    global _film_titles
    index = await tvdb.get_award_index(tvdb_key)
    if _film_titles and _film_titles[0] == id(index):
        return _film_titles[1]
    titles: dict[str, list[tuple[dict, dict, dict]]] = {}
    for award, category, nominees in index:
        if award.get("name") not in tvdb.FILM_AWARDS:
            continue
        for nominee in nominees:
            for key in _title_keys(nominee.get("movie")):
                titles.setdefault(key, []).append((award, category, nominee))
    _film_titles = (id(index), titles)
    return titles


async def _series_title_index(tvdb_key: str) -> dict[str, list[tuple[dict, dict, dict]]]:
    """Series nominees of the Golden Globes and Emmys, keyed by title."""
    global _series_titles
    index = await tvdb.get_award_index(tvdb_key)
    if _series_titles and _series_titles[0] == id(index):
        return _series_titles[1]
    titles: dict[str, list[tuple[dict, dict, dict]]] = {}
    for award, category, nominees in index:
        if family(award.get("name")) not in TV_FAMILIES:
            continue
        for nominee in nominees:
            for key in _title_keys(nominee.get("series")):
                titles.setdefault(key, []).append((award, category, nominee))
    _series_titles = (id(index), titles)
    return titles


async def person_awards(person_id: int, tvdb_key: str, tmdb_key: str | None) -> list[dict]:
    """A person's Oscar, Golden Globe, BAFTA and Emmy nominations and wins."""
    hit = _person_cache.get(person_id) or disk_cache.load("person_awards_v2", person_id, _TTL)
    if hit and time.time() - hit[0] < _TTL:
        _person_cache[person_id] = hit
        return hit[1]

    from routers.shows import _name_award_nominees  # avoid a circular import

    person = await tmdb.get_person(person_id, api_key=tmdb_key)
    gender = person.get("gender")
    name = (person.get("name") or "").lower()
    credits = person.get("combined_credits") or {}

    movies: dict[int, dict] = {}
    shows: dict[int, dict] = {}
    for role, entries in (("cast", credits.get("cast") or []), ("crew", credits.get("crew") or [])):
        for c in entries:
            target = movies if c.get("media_type") == "movie" else shows if c.get("media_type") == "tv" else None
            if target is None or not c.get("id"):
                continue
            entry = target.setdefault(c["id"], {
                "title": c.get("title") or c.get("name"),
                "original_title": c.get("original_title") or c.get("original_name"),
                "year": _year(c.get("release_date") or c.get("first_air_date")),
                "cast": False,
                "jobs": set(),
            })
            if role == "cast":
                entry["cast"] = True
            else:
                entry["jobs"].add(c.get("job"))

    def relevant(kind: str | None, category: str, credit: dict) -> bool:
        if kind == "acting":
            return credit["cast"] and _gender(category) in (None, gender)
        jobs = topic_jobs(category)
        return bool(jobs and credit["jobs"] & (jobs[0] | jobs[1]))

    film_titles = await _film_title_index(tvdb_key)
    candidate_movies = []
    for movie_id, credit in movies.items():
        keys = {norm_title(credit["title"]), norm_title(credit["original_title"])} - {""}
        for key in keys:
            if any(
                relevant(role_kind(c.get("name")), c.get("name"), credit)
                and credit["year"] and _year((n.get("movie") or {}).get("year")) in (credit["year"] - 1, credit["year"], credit["year"] + 1)
                for _, c, n in film_titles.get(key, [])
            ):
                candidate_movies.append(movie_id)
                break

    series_titles = await _series_title_index(tvdb_key)
    candidate_shows: dict[int, int] = {}  # TMDB show id -> TVDB series id
    for show_id, credit in shows.items():
        if not credit["cast"]:
            continue  # TV awards are matched to people through the character they played
        for key in {norm_title(credit["title"]), norm_title(credit["original_title"])} - {""}:
            match = next((
                n["series"]["id"] for _, c, n in series_titles.get(key, [])
                if role_kind(c.get("name")) == "acting" and _PLAYED.search(n.get("details") or "")
                and credit["year"] and _year(n["series"].get("year")) in (credit["year"] - 1, credit["year"], credit["year"] + 1)
            ), None)
            if match:
                candidate_shows[show_id] = match
                break

    semaphore = asyncio.Semaphore(4)
    rows: list[dict] = []

    async def from_film(movie_id: int):
        async with semaphore:
            try:
                awards = await film_awards(movie_id, tvdb_key, tmdb_key)
            except Exception as e:
                print(f"Film awards failed for {movie_id}: {e}")
                return
        for a in awards:
            if person_id in a.get("person_ids", []):
                rows.append(_person_row(a, movies[movie_id]["title"], "movie", movie_id))

    async def from_show(show_id: int, series_id: int):
        async with semaphore:
            try:
                awards = [a for a in await tvdb.get_series_awards(series_id, tvdb_key) if family(a["award_name"]) in TV_FAMILIES]
                awards = await _name_award_nominees(awards, show_id, tmdb_key)
            except Exception as e:
                print(f"Series awards failed for {show_id}: {e}")
                return
        for a in awards:
            if name and name in [p.lower() for p in split_names(a.get("person_name"))]:
                rows.append(_person_row(a, shows[show_id]["title"], "series", show_id))

    await asyncio.gather(
        *(from_film(m) for m in candidate_movies),
        *(from_show(s, t) for s, t in candidate_shows.items()),
    )

    # Wikidata adds anything not already found (by award, year, role and work).
    def key(fam, year, kind, work):
        return fam, year, kind, norm_title(work)

    seen = set()
    for r in rows:
        y = _year(r["year"])
        for d in (-1, 0, 1):
            seen.add(key(family(r["award_name"]), y + d if y else None, role_kind(r["category_name"]), r["work_title"]))
    for w in await wikidata.person_awards(person_id):
        # TV awards are only the Golden Globes and Emmys.
        is_tv = w["work_tv_tmdb_id"] or "television" in w["award_label"].lower()
        if is_tv and family(w["award_name"]) not in TV_FAMILIES:
            continue
        k = key(family(w["award_name"]), _year(w["year"]), role_kind(w["category_name"]), w["work_name"])
        if k in seen:
            continue
        seen.add(k)
        work_id = w["work_movie_tmdb_id"] or w["work_tv_tmdb_id"]
        rows.append({
            "award_name": w["award_name"],
            "category_name": w["category_name"],
            "year": w["year"],
            "is_winner": w["is_winner"],
            "details": None,
            "work_title": w["work_name"],
            "work_type": "movie" if w["work_movie_tmdb_id"] else "series" if w["work_tv_tmdb_id"] else None,
            "work_tmdb_id": work_id,
        })

    rows = _dedupe([r for r in rows if _theirs(r, movies, shows)], "work_title")
    _person_cache[person_id] = (time.time(), rows)
    disk_cache.save("person_awards_v2", person_id, rows)
    return rows


_PLAYED = re.compile(r'For playing', re.I)


# Categories that honour a production as a whole.
_PRODUCTION = re.compile(r"picture|\bfilm\b|series|program|special(?! award| achievement)|movie|miniseries|anthology", re.I)
# Performances role_kind doesn't call acting.
_PERFORMING = re.compile(r"narrat|host|ensemble|voice", re.I)


def _theirs(row: dict, movies: dict[int, dict], shows: dict[int, dict]) -> bool:
    """Whether an award is the person's own. Performances always are; awards
    for the production itself or a behind-the-camera job (best picture,
    writing...) only where they're credited behind the camera on that title,
    so an actor doesn't collect the film's awards. Anything else (a special
    award, say) stays."""
    category = row["category_name"] or ""
    if role_kind(category) == "acting" or _PERFORMING.search(category):
        return True
    if not (role_kind(category) or topic_jobs(category) or _PRODUCTION.search(category)):
        return True
    credits = movies if row.get("work_type") == "movie" else shows if row.get("work_type") == "series" else None
    credit = credits.get(row.get("work_tmdb_id")) if credits is not None else None
    if credit is not None:
        return bool(credit["jobs"] - {None})
    # No title to check against: theirs if they work behind the camera at all.
    return any(c["jobs"] - {None} for c in (*movies.values(), *shows.values()))


def _person_row(award: dict, title: str, work_type: str, work_id: int) -> dict:
    return {
        "award_name": award["award_name"],
        "category_name": award["category_name"],
        "year": award["year"],
        "is_winner": award["is_winner"],
        "details": award.get("details"),
        # Attributed to the person by a guessed name (see _name_film_awards).
        "name_inferred": bool(award.get("name_inferred")),
        "work_title": title,
        "work_type": work_type,
        "work_tmdb_id": work_id,
    }
