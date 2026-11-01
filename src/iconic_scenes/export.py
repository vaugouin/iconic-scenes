"""Flat export of the results: data/iconic-scenes.csv, one row per line of data/quotes.csv.

The row holds everything the results page shows, so the page (report.py) is rendered from these rows,
and another front end (a MariaDB table read by tmdb-front) can rebuild the same page from the CSV alone."""
import csv
import json
import re

from . import config, pipeline

CSV = config.DATA / "iconic-scenes.csv"
SQL = config.DATA / "iconic-scenes.sql"
DB_STILL_PATH = "iconic-scenes/"     # tmdb-front serves the stills from a read-only mount of shared_data/iconic-scenes
FIELDS = ["rank", "id", "status", "quote", "lang", "title", "year", "tmdb_id", "actor", "character",
          "still_path", "still_file", "alt1_file", "alt2_file", "timecode", "seconds", "subtitle_text",
          "source", "match_score", "faces", "sharpness", "source_height", "hdr",
          "copy_file", "copy_edition", "copy_duration", "copy_runtime", "copy_resolution", "copy_size",
          "copy_plex_key", "copy_part_id", "copy_count", "other_copies"]
SOURCES = {"speech": "reconnaissance vocale locale", "sidecar": "sous-titres Plex, fichier externe",
           "embedded": "sous-titres Plex, piste intégrée"}


def timecode(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def split_who(who: str) -> tuple[str, str]:
    """"Robert De Niro (Travis Bickle)" -> ("Robert De Niro", "Travis Bickle")."""
    m = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", who or "")
    return (m.group(1), m.group(2)) if m else (who or "", "")


def source_kind(r: dict) -> str:
    track = r.get("track") or {}
    if str(track.get("id", "")).startswith("asr-"):
        return "speech"
    return "sidecar" if track.get("external") else "embedded"


def clean(text: str) -> str:
    """Drop control characters (some sidecar files carry NUL bytes, which MariaDB rejects) and squeeze spaces."""
    return " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", text or "").split())


def short_path(file: str) -> str:
    """Library folder and file name ("HDFilms/Alien 1979 ....mkv"): the timecode is valid for this file only."""
    return "/".join((file or "").replace("\\", "/").split("/")[-2:])


def copy_label(c: dict) -> str:
    return ", ".join(x for x in (c.get("edition") or "", timecode(c.get("duration") or 0),
                                 f"{c.get('width')}x{c.get('height')}", short_path(c.get("file"))) if x)


def copy_fields(r: dict) -> dict:
    """The copy the line was read from (its timecode is valid for that file only) and the film's other copies."""
    cs = r.get("copies") or []
    used = next((c for c in cs if c["id"] == r.get("copy_id")), None) or next((c for c in cs if c["file"] == r.get("file")), None)
    out = dict(copy_count=len(cs) or "", other_copies=" | ".join(copy_label(c) for c in cs if c is not used))
    if used:
        out.update(copy_file=short_path(used["file"]), copy_edition=used.get("edition") or "",
                   copy_duration=used.get("duration") or "", copy_runtime=timecode(used.get("duration") or 0),
                   copy_resolution=f"{used.get('width')}x{used.get('height')}", copy_size=used.get("size") or "",
                   copy_plex_key=used.get("rating_key") or "", copy_part_id=used["id"])
    elif r.get("file"):
        out.update(copy_file=short_path(r["file"]))
    return out


def row(rank: int, q: dict, r: dict | None) -> dict:
    actor, character = split_who(q["who"])
    out = dict(rank=rank, id=q["id"], status=r["status"] if r else "not run", quote=q["quote"], lang=q["lang"],
               title=q["title"], year=int(q["year"]), tmdb_id=(r or {}).get("tmdb_id") or q.get("tmdb_id") or "",
               actor=actor, character=character)
    if r:
        out.update(copy_fields(r))
    if r and r["status"] == "ok":
        alts = r.get("alternates", []) + ["", ""]
        best, m = r["best"], r["match"]
        out.update(still_path="img/", still_file=r["still"], alt1_file=alts[0], alt2_file=alts[1],
                   timecode=timecode(best["t"]), seconds=round(best["t"], 2), subtitle_text=clean(m["text"]),
                   source=source_kind(r), match_score=round(m["score"], 1), faces=best["faces"],
                   sharpness=round(best["sharp"]), source_height=r["source_height"], hdr=int(bool(r.get("hdr"))))
    return out


def rows() -> list[dict]:
    out = []
    for rank, q in enumerate(pipeline.quotes(), 1):
        f = pipeline.RESULTS / f"{q['id']}.json"
        out.append(row(rank, q, json.loads(f.read_text(encoding="utf-8")) if f.exists() else None))
    return out


# CSV field -> T_WC_ICONIC_SCENE column (doc/sql/T_WC_ICONIC_SCENE.sql)
COLUMNS = dict(id="SCENE_KEY", status="STATUS", quote="QUOTE", lang="LANG", title="TITLE", year="RELEASE_YEAR",
               tmdb_id="ID_MOVIE", actor="ACTOR_NAME", character="CHARACTER_NAME", still_path="STILL_PATH",
               still_file="STILL_FILE", alt1_file="ALT1_FILE", alt2_file="ALT2_FILE", timecode="TIMECODE",
               seconds="SECONDS", subtitle_text="SUBTITLE_TEXT", source="SOURCE", match_score="MATCH_SCORE",
               faces="FACE_COUNT", sharpness="SHARPNESS", source_height="SOURCE_HEIGHT", hdr="IS_HDR",
               copy_file="COPY_FILE", copy_edition="COPY_EDITION", copy_duration="COPY_DURATION", copy_runtime="COPY_RUNTIME",
               copy_resolution="COPY_RESOLUTION", copy_size="COPY_SIZE", copy_plex_key="COPY_PLEX_KEY",
               copy_part_id="COPY_PART_ID", copy_count="COPY_COUNT", other_copies="OTHER_COPIES", rank="DISPLAY_ORDER")


def sql_value(v) -> str:
    if v is None or v == "":
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def write_sql(data: list[dict]) -> str:
    """Upsert of every row, keyed on SCENE_KEY; rows no longer in quotes.csv are flagged DELETED."""
    cols = list(COLUMNS.values())
    lines = ["-- Generated by `iconic-scenes export` from data/iconic-scenes.csv. Run after doc/sql/T_WC_ICONIC_SCENE.sql.",
             "SET NAMES utf8mb4;"]
    for r in data:
        vals = [sql_value(dict(r, still_path=DB_STILL_PATH if r.get("still_file") else "").get(k)) for k in COLUMNS]
        lines.append(f"INSERT INTO T_WC_ICONIC_SCENE ({', '.join(cols)}, DELETED, DAT_CREAT, TIM_UPDATED) "
                     f"VALUES ({', '.join(vals)}, 0, CURDATE(), NOW()) ON DUPLICATE KEY UPDATE "
                     + ", ".join(f"{c} = VALUES({c})" for c in cols[1:]) + ", DELETED = 0, TIM_UPDATED = NOW();")
    keys = ", ".join(sql_value(r["id"]) for r in data)
    lines.append(f"UPDATE T_WC_ICONIC_SCENE SET DELETED = 1, TIM_UPDATED = NOW() WHERE SCENE_KEY NOT IN ({keys});")
    lines.append("SELECT STATUS, COUNT(*) FROM T_WC_ICONIC_SCENE WHERE DELETED = 0 GROUP BY STATUS;")
    SQL.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(SQL)


def write() -> str:
    data = rows()
    with open(CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(data)
    write_sql(data)
    return str(CSV)
