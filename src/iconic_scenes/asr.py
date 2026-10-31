"""Last resort when a copy has no subtitle track in the wanted language: local speech recognition.

faster-whisper runs on the CPU, offline, no API call. The audio has to be read from the NAS in full
(about a minute for a 3 GB file at 50 MB/s, much longer when the NAS is busy), then transcribed (about ten minutes)."""
import json
import subprocess
import wave

import numpy as np

from . import config
from .subtitles import ISO

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MODEL = config.get("ICONIC_WHISPER_MODEL", "small")


def audio_index(part: dict, lang: str) -> int | None:
    """Stream index of the first audio track in `lang` (a dubbed copy often lists the French track first)."""
    for a in part.get("audio", []):
        if ISO.get((a.get("lang") or "").lower()) == lang:
            return a["index"]
    return None


def has_audio(part: dict, lang: str) -> bool:
    """True when the copy has an audio track in `lang`, or a single untagged one."""
    return audio_index(part, lang) is not None or (len(part.get("audio", [])) == 1 and not part["audio"][0].get("lang"))


def cues(part: dict, lang: str) -> list[dict]:
    """Speech segments of a copy as subtitle-like cues {start, end, text}, cached in work/asr/."""
    cache = config.WORK / "asr" / f"{part['id']}-{lang}-{MODEL}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    cache.parent.mkdir(parents=True, exist_ok=True)
    wav = cache.with_suffix(".wav")
    if not wav.exists():
        index = audio_index(part, lang)
        stream = ["-map", f"0:{index}"] if index is not None else []
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", part["file"], *stream, "-vn", "-sn",
                        "-ac", "1", "-ar", "16000", str(wav)], check=True, creationflags=NO_WINDOW, timeout=7200)
    with wave.open(str(wav)) as w:                    # decode ourselves: faster-whisper's PyAV decoder breaks on recent PyAV
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    segments, _ = _model().transcribe(audio, language=lang, vad_filter=True, beam_size=1,
                                      condition_on_previous_text=False)
    out = [dict(start=round(s.start, 2), end=round(s.end, 2), text=s.text.strip()) for s in segments if s.text.strip()]
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    wav.unlink()
    return out


_MODELS = {}


def _model():
    if MODEL not in _MODELS:
        from faster_whisper import WhisperModel      # heavy import, only when needed
        _MODELS[MODEL] = WhisperModel(MODEL, device="cpu", compute_type="int8")
    return _MODELS[MODEL]


def words(part: dict, lang: str, start: float, end: float, margin: float = 4.0) -> list[dict]:
    """Second pass on a short window: one cue per word, with word timestamps.

    The whole-film pass is greedy and its segments can span half a minute of music and speech; re-reading
    only the window (a few MB, an input seek) with a wider beam and no VAD gives sharper words and times."""
    a = max(0.0, start - margin)
    index = audio_index(part, lang)
    stream = ["-map", f"0:{index}"] if index is not None else []
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{a:.2f}", "-t", f"{end - a + margin:.2f}",
                          "-i", part["file"], *stream, "-vn", "-sn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         check=True, capture_output=True, creationflags=NO_WINDOW, timeout=600).stdout
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    segments, _ = _model().transcribe(audio, language=lang, beam_size=5, word_timestamps=True,
                                      condition_on_previous_text=False)
    return [dict(start=round(a + w.start, 2), end=round(a + w.end, 2), text=w.word.strip())
            for s in segments for w in (s.words or []) if w.word.strip()]
