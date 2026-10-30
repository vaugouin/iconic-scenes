"""Subtitle text for one copy of a film: Plex sidecar download or ffmpeg extraction of an embedded track."""
import re
import subprocess
from pathlib import Path

import pysubs2

from . import config, plex

TEXT_CODECS = {"srt", "subrip", "ass", "ssa", "mov_text", "webvtt", "vtt", "text"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
STOPWORDS = {
    "en": set("the you and that what this have not are was for with but your just don know there they can get here".split()),
    "fr": set("les est pas que vous une des pour qui dans sur avec mais tout cette elle nous suis rien bien fait".split()),
}
ISO = {"eng": "en", "en": "en", "fra": "fr", "fre": "fr", "fr": "fr"}


def guess_lang(text: str) -> str | None:
    words = re.findall(r"[a-zà-ÿ']+", text.lower())
    counts = {lang: sum(w in sw for w in words) for lang, sw in STOPWORDS.items()}
    best = max(counts, key=counts.get)
    return best if counts[best] > 50 and counts[best] > 2 * min(counts.values()) else None


def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def load(text: str) -> list[dict]:
    """Cues as dicts {start, end, text} in seconds, tags and line breaks flattened."""
    subs = pysubs2.SSAFile.from_string(text)
    cues = []
    for ev in subs:
        if ev.is_comment:
            continue
        body = " ".join(ev.plaintext.split())
        if body:
            cues.append(dict(start=ev.start / 1000, end=ev.end / 1000, text=body))
    return cues


def candidates(part: dict, lang: str) -> list[dict]:
    """Text subtitle streams of a copy that may be in `lang`, full tracks first (forced and SDH last)."""
    out = []
    for s in part["subs"]:
        if s.get("codec") not in TEXT_CODECS:
            continue
        code = ISO.get((s.get("languageCode") or "").lower())
        if code and code != lang:
            continue
        rank = (bool(s.get("forced")) or "forced" in str(s.get("title", "")).lower(), bool(s.get("hearingImpaired")), code is None)
        out.append((rank, s))
    return [s for _, s in sorted(out, key=lambda x: x[0])]


def cached(stream: dict) -> bool:
    return (config.WORK / "subs" / f"{stream['id']}.txt").exists()


def fetch(part: dict, stream: dict) -> str:
    """Raw subtitle text, cached in work/subs/<stream id>.srt."""
    cache = config.WORK / "subs" / f"{stream['id']}.txt"
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    if stream.get("key"):
        text = decode(plex.download(stream["key"]))
    else:
        tmp = cache.with_suffix(".srt")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", part["file"],
                        "-map", f"0:{stream['index']}", "-c:s", "srt", str(tmp)],
                       check=True, creationflags=NO_WINDOW, timeout=1800)
        text = decode(tmp.read_bytes())
        tmp.unlink()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding="utf-8")
    return text
