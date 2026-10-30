"""Plex HTTP API (same access as open-credits) and its local TMDb index."""
import json
import re
import sqlite3
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from . import config


def _url(path: str, **query) -> str:
    query["X-Plex-Token"] = config.get("PLEX_TOKEN")
    return config.get("PLEX_SERVER_URL").rstrip("/") + path + ("&" if "?" in path else "?") + urllib.parse.urlencode(query)


def get(path: str, timeout: int = 60, tries: int = 3, **query) -> dict:
    req = urllib.request.Request(_url(path, **query), headers={"Accept": "application/json"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)["MediaContainer"]
        except (TimeoutError, urllib.error.URLError):
            if attempt == tries - 1:
                raise
            time.sleep(3)


def download(path: str, timeout: int = 60) -> bytes:
    with urllib.request.urlopen(_url(path), timeout=timeout) as r:
        return r.read()


def local(plex_path: str) -> str:
    for plex_prefix, local_prefix in config.path_map():
        if plex_path.startswith(plex_prefix + "/"):
            return local_prefix + "/" + plex_path[len(plex_prefix) + 1:]
    return plex_path


def norm_title(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return re.sub(r"^(the|le|la|les|l) ", "", text)


def find_movie(title: str, year: int, tmdb_id: int | None = None) -> list[dict]:
    """Plex movies matching a title (accent and article insensitive) within a year of `year`.

    Reads the open-credits index (plex_movie: rating_key, tmdb_movie_id, title, year, added_at, file)."""
    con = sqlite3.connect(f"file:{config.OC_INDEX.as_posix()}?mode=ro", uri=True)
    if tmdb_id:
        rows = con.execute("SELECT rating_key, tmdb_movie_id, title, year FROM plex_movie WHERE tmdb_movie_id = ?", (tmdb_id,)).fetchall()
        con.close()
        return [dict(rating_key=r[0], tmdb_id=r[1], title=r[2], year=r[3]) for r in rows]
    rows = con.execute(
        "SELECT rating_key, tmdb_movie_id, title, year FROM plex_movie WHERE year BETWEEN ? AND ?", (year - 1, year + 1)
    ).fetchall()
    con.close()
    wanted = norm_title(title)
    hits = [dict(rating_key=r[0], tmdb_id=r[1], title=r[2], year=r[3]) for r in rows if norm_title(r[2] or "") == wanted]
    return sorted(hits, key=lambda h: abs(h["year"] - year))


def movie(rating_key: int) -> dict:
    """Plex metadata of a movie, cached in work/plex/ (the server can be slow to answer)."""
    cached = config.WORK / "plex" / f"{rating_key}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    meta = get(f"/library/metadata/{rating_key}")["Metadata"][0]
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(meta), encoding="utf-8")
    return meta


def parts(meta: dict) -> list[dict]:
    """Every single-file copy of a movie with its video facts and subtitle streams."""
    out = []
    for media in meta.get("Media", []):
        if len(media.get("Part", [])) != 1:
            continue
        part = media["Part"][0]
        video = next((s for s in part.get("Stream", []) if s.get("streamType") == 1), {})
        subs = [s for s in part.get("Stream", []) if s.get("streamType") == 3]
        out.append(dict(
            id=part["id"], file=local(part["file"]), size=part.get("size", 0), height=media.get("height") or 0,
            resolution=media.get("videoResolution"), hdr=bool(video.get("DOVIPresent") or "smpte2084" in str(video.get("colorTrc", ""))
                                                               or "HDR" in str(video.get("displayTitle", ""))),
            dovi=bool(video.get("DOVIPresent")), subs=subs,
        ))
    return out
