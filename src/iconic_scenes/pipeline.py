"""One quote, end to end: Plex copy -> subtitle track -> matched cues -> frames -> best still."""
import csv
import json
import shutil
import traceback
from pathlib import Path

import cv2

from . import asr, config, frames, locate, plex, score, subtitles

MIN_SCORE = 80
GOOD_SCORE = 88
SPEECH_FLOOR = 55       # weak speech matches above this get a second, word-level look
PRE, POST, FPS = 2.5, 3.0, 5      # frame window around the matched cues, in seconds, and sampling rate
RESULTS = config.WORK / "results"
# demuxing an embedded track reads the whole file: ~1 min per 3 GB at 50 MB/s, but remuxes of 40 to 130 GB are skipped
EMBEDDED_MAX = float(config.get("ICONIC_EMBEDDED_MAX", "30e9"))


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
        first = q.get("occurrence") == "first"
        if hit and (best is None or hit["score"] > best[2]["score"] + (2 if first else 0)
                    or first and hit["score"] >= best[2]["score"] - 2 and hit["start"] < best[2]["start"]):
            best = (part, stream, hit)
        # an explicit "first" checks every track: some leave the first utterance unsubtitled (Citizen Kane's dying "Rosebud")
        if best and best[2]["score"] >= 97 and not first:
            break
    return best if best and best[2]["score"] >= MIN_SCORE else None


def _word_pass(q: dict, part: dict, segs: list[dict], cand: dict) -> dict | None:
    """Re-transcribe a coarse match word by word: each segment alone (a window spanning minutes transcribes
    worse, Le Corniaud's 41 s segment sat next to a 132 s one), then the whole span if the line straddles segments."""
    spans = [(s["start"], s["end"]) for s in segs[cand["first"]:cand["last"] + 1]]
    if len(spans) > 1:
        spans.append((cand["start"], cand["end"]))
    best = None
    for a, b in spans:
        f = locate.find(q["quote"], asr.words(part, q["lang"], a, b))
        if f and (best is None or f["score"] > best["score"]):
            best = f
    return best


def save_still(src, crop, dest):
    img = cv2.imread(str(src))
    x, y, w, h = crop
    cv2.imwrite(str(dest), img[y:y + h, x:x + w], [cv2.IMWRITE_JPEG_QUALITY, 92])


def pick(video: str, a: float, b: float, name: str, img_dir, pre: float = PRE, post: float = POST,
         fps: float = FPS, alternates: int = 2) -> dict | None:
    """Best still (and runners-up at least a second apart) for the span a..b seconds of one file.
    Writes <name>.jpg and <name>-altN.jpg into img_dir; returns what was picked, None when no frame came out."""
    info = frames.probe(video)
    work = config.WORK / "frames" / name
    cand = frames.extract(video, a - pre, b + post, work, fps=fps, hdr=info["hdr"])
    if not cand:
        return None
    best, details = score.choose(cand, (a, b))
    order = sorted(range(len(details)), key=lambda i: -details[i]["total"])
    picks = [best]
    for i in order:
        if len(picks) == alternates + 1:
            break
        if all(abs(details[i]["t"] - details[j]["t"]) >= 1.0 for j in picks):
            picks.append(i)
    img_dir = Path(img_dir)
    img_dir.mkdir(parents=True, exist_ok=True)
    names = []
    for rank, i in enumerate(picks):
        fname = f"{name}.jpg" if rank == 0 else f"{name}-alt{rank}.jpg"
        save_still(cand[i][1], details[i]["crop"], img_dir / fname)
        names.append(fname)
    shutil.rmtree(work, ignore_errors=True)
    return dict(hdr=info["hdr"], source_height=info["height"], frames=len(cand), still=names[0],
                alternates=names[1:], best=details[best], picked=[details[i] for i in picks])


def span_still(video: str, start: float, end: float, name: str, img_dir, pre: float = 0.0, post: float = 0.0,
               fps: float = FPS, alternates: int = 2) -> dict:
    """Entry point for callers that already know the moment (source-to-screen): a fixed file and a time span
    in, the best still out. No Plex lookup and no subtitle search: the timecode is valid for this file only,
    so the result names the file and its duration. Spans over 60 s are sampled more sparsely."""
    length = max(0.0, end - start) + pre + post
    rate = fps if length <= 12 else max(0.5, min(fps, 60 / max(length, 1e-6)))
    picked = pick(video, start, end, name, img_dir, pre=pre, post=post, fps=rate, alternates=alternates)
    info = frames.probe(video)
    return dict(file=video, duration=info["duration"], start=start, end=end, fps=rate, name=name,
                img_dir=str(img_dir), status="ok" if picked else "no frames", **(picked or {}))


COPY_KEYS = ("id", "rating_key", "edition", "duration", "width", "height", "size", "file")


def copies(parts: list[dict]) -> list[dict]:
    """What identifies each copy of the film, so a timecode can be tied to the exact file it was read from:
    editions (Director's Cut, Extended...) and even rips of one edition differ in length."""
    return [{k: p.get(k) for k in COPY_KEYS} for p in parts]


def refresh_copies(q: dict, fresh: bool = False) -> dict | None:
    """Re-list the Plex copies of a line's film into its result, without redoing the line.
    fresh=True asks Plex again instead of work/plex/, to see copies added or removed since the run.
    copy_id stays None when the file the line was read from is no longer in Plex: rerun the line then."""
    out = RESULTS / f"{q['id']}.json"
    if not out.exists():
        return None
    res = json.loads(out.read_text(encoding="utf-8"))
    hits = plex.find_movie(q["title"], int(q["year"]), int(q["tmdb_id"]) if q.get("tmdb_id") else None)
    if not hits:
        return res
    tmdb = hits[0]["tmdb_id"]
    if fresh:
        for h in hits:
            (config.WORK / "plex" / f"{h['rating_key']}.json").unlink(missing_ok=True)
    parts = [p for h in hits if h["tmdb_id"] == tmdb for p in plex.parts(plex.movie(h["rating_key"]))]
    res["copies"] = copies(parts)
    if res.get("file"):
        res["copy_id"] = next((p["id"] for p in parts if p["file"] == res["file"]), None)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


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
        # one film can be split over several Plex items (one per library or unmerged copy): pool their copies
        parts = [p for h in hits if h["tmdb_id"] == movie["tmdb_id"] for p in plex.parts(plex.movie(h["rating_key"]))]
        res["copies"] = copies(parts)
        found = find_line(q, parts, res["log"], embedded)
        if not found and speech:
            # smallest copy that speaks the line's language, SDR before HDR (the frames come from it too)
            part = min(parts, key=lambda p: (not asr.has_audio(p, q["lang"]), p["dovi"], p["hdr"], p["size"]))
            segs = asr.cues(part, q["lang"])
            hit = locate.find(q["quote"], segs, q.get("occurrence", ""))
            res["log"].append(f"speech recognition ({asr.MODEL}) on {part['file']}: score {hit and hit['score']}")
            # second pass, word level, on the best match, or on the five best when none is convincing (the greedy
            # whole-film pass mishears: Le Mepris's "mes fesses" scene came out as "Je lis mes fesses")
            looks = [hit] if hit and hit["score"] >= MIN_SCORE else locate.windows(q["quote"], segs, 5, SPEECH_FLOOR)
            for cand in looks:
                fine = _word_pass(q, part, segs, cand)
                res["log"].append(f"word pass {cand['start']:.1f}-{cand['end']:.1f} (coarse {cand['score']}): "
                                  f"score {fine and fine['score']}")
                if fine and fine["score"] >= max(cand["score"], MIN_SCORE - 5) and (
                        "coarse" not in (hit or {}) or fine["score"] > hit["score"]):
                    hit = dict(fine, text=fine["text"].replace(" / ", " "),
                               coarse=dict(start=cand["start"], end=cand["end"], score=cand["score"]))
            if hit and hit["score"] >= MIN_SCORE - (5 if "coarse" in hit else 0):
                found = (part, dict(id=f"asr-{part['id']}", title=f"speech recognition (faster-whisper {asr.MODEL})"), hit)
        if not found:
            res["status"] = "line not found"
            return res
        part, stream, hit = found
        res.update(file=part["file"], copy_id=part["id"], track=dict(id=stream["id"], title=stream.get("title"), external=bool(stream.get("key"))),
                   match=hit)
        a, b = hit["start"], min(hit["end"], hit["start"] + 12)
        picked = pick(part["file"], a, b, q["id"], config.SITE / "img")
        if not picked:
            res["status"] = "no frames"
            return res
        res.update(status="ok", **picked)
    except Exception:                                      # noqa: BLE001 - keep the batch going, record why
        res["log"].append(traceback.format_exc(limit=3))
    finally:
        RESULTS.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res
