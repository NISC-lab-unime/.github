#!/usr/bin/env python3
"""Fetch publications from OpenAlex for NISC Lab professors and update the profile README."""

import json
import re
import sys
import urllib.request
from pathlib import Path

ORCIDS = [
    "0000-0002-8957-5307",  # Prof. Giorgio Mario Grasso
    "0000-0003-3666-061X",  # Prof. Alessio Plebe
    "0000-0002-3633-098X",  # Prof. Pietro Perconti
]

FETCH_PER_AUTHOR = 50
MIN_YEAR = 2018
MAX_DISPLAY = 10
MAILTO = "noreply@example.com"
FULL_LIST_URL = "https://nisc.unime.it/?page_id=839"
README_PATH = Path(__file__).resolve().parent.parent / "profile" / "README.md"


def fetch_works(orcid: str) -> list[dict]:
    url = (
        f"https://api.openalex.org/works"
        f"?filter=authorships.author.orcid:https://orcid.org/{orcid}"
        f"&sort=publication_date:desc"
        f"&per-page={FETCH_PER_AUTHOR}"
        f"&select=id,doi,ids,display_name,publication_year,publication_date,"
        f"type,primary_location,authorships"
        f"&mailto={MAILTO}"
    )
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req) as res:
            data = json.loads(res.read())
        results = data.get("results", []) if isinstance(data, dict) else []
    except Exception as exc:
        print(f"  [warn] fetch failed for {orcid}: {exc}", file=sys.stderr)
        return []

    works = []
    for w in results:
        doi = (w.get("doi") or (w.get("ids") or {}).get("doi") or "").removeprefix(
            "https://doi.org/"
        )
        works.append({
            "doi": doi,
            "title": w.get("display_name", "untitled"),
            "year": w.get("publication_year"),
            "date": w.get("publication_date", ""),
            "journal": _journal_name(w),
            "authors": _author_names(w),
            "url": _best_url(w),
        })
    return works


def _journal_name(work: dict) -> str:
    loc = work.get("primary_location") or {}
    src = loc.get("source") or {}
    return src.get("display_name") or (work.get("host_venue") or {}).get("display_name") or ""


def _author_names(work: dict) -> str:
    names = [
        a.get("author", {}).get("display_name", "").strip()
        for a in (work.get("authorships") or [])
    ]
    names = [n for n in names if n]
    if not names:
        return ""
    if len(names) <= 6:
        return ", ".join(names)
    return ", ".join(names[:6]) + " et al."


def _best_url(work: dict) -> str:
    loc = work.get("primary_location") or {}
    return (
        loc.get("landing_page_url")
        or (loc.get("source") or {}).get("homepage_url")
        or (work.get("ids") or {}).get("doi")
        or (f"https://doi.org/{work['doi']}" if work.get("doi") else "")
        or "#"
    )


def dedupe(works: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for w in works:
        key = w["doi"] or f"{w['title'].strip().lower()}__{w.get('year') or 'na'}"
        if key not in seen:
            seen[key] = w
        else:
            existing = seen[key]
            score_old = (1 if existing["date"] else 0) + (1 if existing["authors"] else 0) + (1 if existing["journal"] else 0)
            score_new = (1 if w["date"] else 0) + (1 if w["authors"] else 0) + (1 if w["journal"] else 0)
            if score_new > score_old:
                seen[key] = w
    return list(seen.values())


def sort_works(works: list[dict]) -> list[dict]:
    return sorted(works, key=lambda w: w.get("date") or f"{w.get('year') or 0}-01-01", reverse=True)


def build_table_rows(works: list[dict]) -> str:
    rows = []
    for i, w in enumerate(works[:MAX_DISPLAY], 1):
        title = _escape_md(w["title"])
        doi_link = f"[{w['doi']}](https://doi.org/{w['doi']})" if w["doi"] else "—"
        authors = _escape_md(w["authors"]) or "—"
        journal = _escape_md(w["journal"]) or "—"
        year = str(w["year"]) if w["year"] else "—"
        rows.append(f"| {i} | {title} | {authors} | {journal} | {year} | {doi_link} | — |")
    return "\n".join(rows)


def _escape_md(text: str) -> str:
    return text.replace("|", "\\|")


def update_readme(rows: str, total: int) -> None:
    content = README_PATH.read_text()
    marker = "| # | Title | Authors | Venue | Year | DOI | Projects |"
    before, _, after = content.partition(marker)
    if not after:
        print("error: could not find publications table header in README", file=sys.stderr)
        sys.exit(1)

    # skip the separator line and the old body rows until the next blank line or "---"
    after_header = after.lstrip("\n")
    sep_end = after_header.find("\n")
    body_start = sep_end + 1 if sep_end != -1 else 0
    remainder = after_header[body_start:]

    # find the end of the table: blank line followed by "---" or end of file
    end_marker = re.search(r"\n(?=\n---|\n##|\Z)", remainder)
    suffix = f"\n\n[View all {total} publications →]({FULL_LIST_URL})\n"
    if end_marker:
        new_content = content[: len(before) + len(marker) + 1 + body_start] + rows + suffix + remainder[end_marker.start():]
    else:
        new_content = before + marker + "\n|---|-------|---------|-------|------|-----|----------|\n" + rows + suffix + "\n"

    README_PATH.write_text(new_content)


def main() -> None:
    print("Fetching publications from OpenAlex...")
    all_works = []
    for orcid in ORCIDS:
        print(f"  fetching {orcid} ...")
        works = fetch_works(orcid)
        print(f"    -> {len(works)} works")
        all_works.extend(works)

    print(f"\nTotal fetched: {len(all_works)}")
    all_works = dedupe(all_works)
    print(f"After deduplication: {len(all_works)}")
    all_works = [w for w in all_works if w["year"] and w["year"] >= MIN_YEAR]
    print(f"After year filter (>={MIN_YEAR}): {len(all_works)}")
    all_works = sort_works(all_works)

    rows = build_table_rows(all_works)
    update_readme(rows, len(all_works))
    print(f"\nWrote {min(len(all_works), MAX_DISPLAY)} of {len(all_works)} publications to {README_PATH}")


if __name__ == "__main__":
    main()
