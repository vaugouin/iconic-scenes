"""One quote, end to end: Plex copy -> subtitle track -> matched cues -> frames -> best still."""
import csv
import json
import shutil
import traceback

import cv2

from . import asr, config, frames, locate, plex, score, subtitles

MIN_SCORE = 80
GOOD_SCORE = 88
PRE, POST, FPS = 2.5, 3.0, 5      # frame window around the matched cues, in seconds, and sampling rate
RESULTS = config.WORK / "results"
EMBEDDED_MAX = float(config.get("ICONIC_EMBEDDED_MAX", "4e9"))   # T: reads at ~3 MB/s: demuxing a big file takes too long


def quotes() -> list[dict]:
    with open(config.DATA / "quotes.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def part_order(part: dict) -> tuple:
    return (part["dovi"], part["hdr"], abs((part["height"] or 1080) - 1080) > 100, part["size"])


def tracks(parts: list[dict], lang: str) -> list[tuple[dict, dict]]:
    """(copy, subtitle stream) pairs to try: sidecar files first (one fast HTTP call each),
    then embedded tracks of the smallest copies (ffmpeg has to read the whole file over the network)."""
    external, embedded = [], []
    for part in sorted(parts, key=part_order):
        for stream in subtitles.candidates(part, lang):
            if stream.get("key"):
                external.append((part, stream))
            elif part["size"] <= EMBEDDED_MAX:
                embedded.append((part, stream))
    return external + sorted(embedded, key=lambda ps: ps[0]["size"])


def find_line(q: dict, parts: list[dict], log: list[str], embedded: bool = True) -> tuple[dict, dict, dict] | None:
    best = None
    for part, stream in tracks(parts, q["lang"]):
        if not stream.get("key") and not subtitles.cached(stream):
            if not embedded or (best and best[2]["score"] >= GOOD_SCORE):
                continue
        try:
            text = subtitles.fetch(part, stream)
        except Exception as exc:                           # noqa: BLE001 - a broken track is skipped, not fatal
            log.append(f"track {stream['id']} unreadable: {exc}")
            continue
        cues = subtitles.load(text)
        lang = subtitles.ISO.get((stream.get("languageCode") or "").lower()) or subtitles.guess_lang(text[:30000])
        if lang != q["lang"] or len(cues) < 100:
            log.append(f"track {stream['id']} skipped (lang {lang}, {len(cues)} cues)")
            continue
        hit = locate.find(q["quote"], cues, q.get("occurrence", ""))
        log.append(f"track {stream['id']} ({'sidecar' if stream.get('key') else 'embedded'}, "
                   f"{stream.get('title') or stream.get('codec')}) score {hit and hit['score']}")
        if hit and (best is None or hit["score"] > best[2]["score"]):
            best = (part, stream, hit)
        if best and best[2]["score"] >= 97:
            break
    return best if best and best[2]["score"] >= MIN_SCORE else None


def save_still(src, crop, dest):
    img = cv2.imread(str(src))
    x, y, w, h = crop
    cv2.imwrite(str(dest), img[y:y + h, x:x + w], [cv2.IMWRITE_JPEG_QUALITY, 92])


def run_one(q: dict, force: bool = False, embedded: bool = True, speech: bool = False) -> dict:
    out = RESULTS / f"{q['id']}.json"
    if out.exists() and not force:
        cached = json.loads(out.read_text(encoding="utf-8"))
        more = embedded > cached.get("embedded_tried", True) or speech > cached.get("speech_tried", False)
        if cached["status"] in ("ok", "not in Plex") or not more:
            return cached
    res = dict(q, status="error", log=[], embedded_tried=embedded, speech_tried=speech)
    try:
        hits = plex.find_movie(q["title"], int(q["year"]), int(q["tmdb_id"]) if q.get("tmdb_id") else None)
        if not hits:
            res["status"] = "not in Plex"
            return res
        movie = hits[0]
        res.update(tmdb_id=movie["tmdb_id"], plex_title=movie["title"], plex_year=movie["year"])
        parts = plex.parts(plex.movie(movie["rating_key"]))
        found = find_line(q, parts, res["log"], embedded)
        if not found and speech:
            part = min((p for p in parts if not p["hdr"]), key=lambda p: p["size"], default=min(parts, key=lambda p: p["size"]))
            hit = locate.find(q["quote"], asr.cues(part, q["lang"]), q.get("occurrence", ""))
            res["log"].append(f"speech recognition ({asr.MODEL}) on {part['file']}: score {hit and hit['score']}")
            if hit and hit["score"] >= MIN_SCORE:
                found = (part, dict(id=f"asr-{part['id']}", title=f"speech recognition (faster-whisper {asr.MODEL})"), hit)
        if not found:
            res["status"] = "line not found"
            return res
        part, stream, hit = found
        res.update(file=part["file"], track=dict(id=stream["id"], title=stream.get("title"), external=bool(stream.get("key"))),
                   match=hit)
        info = frames.probe(part["file"])
        a, b = hit["start"], min(hit["end"], hit["start"] + 12)
        work = config.WORK / "frames" / q["id"]
        cand = frames.extract(part["file"], a - PRE, b + POST, work, fps=FPS, hdr=info["hdr"])
        if not cand:
            res["status"] = "no frames"
            return res
        best, details = score.choose(cand, (a, b))
        order = sorted(range(len(details)), key=lambda i: -details[i]["total"])
        picks = [best]
        for i in order:                                    # two runners-up at least a second away from the others
            if len(picks) == 3:
                break
            if all(abs(details[i]["t"] - details[j]["t"]) >= 1.0 for j in picks):
                picks.append(i)
        img_dir = config.SITE / "img"
        img_dir.mkdir(parents=True, exist_ok=True)
        names = []
        for rank, i in enumerate(picks):
            name = f"{q['id']}.jpg" if rank == 0 else f"{q['id']}-alt{rank}.jpg"
            save_still(cand[i][1], details[i]["crop"], img_dir / name)
            names.append(name)
        res.update(status="ok", hdr=info["hdr"], source_height=info["height"], frames=len(cand), still=names[0],
                   alternates=names[1:], best=details[best], picked=[details[i] for i in picks])
        shutil.rmtree(work, ignore_errors=True)
    except Exception:                                      # noqa: BLE001 - keep the batch going, record why
        res["log"].append(traceback.format_exc(limit=3))
    finally:
        RESULTS.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res
