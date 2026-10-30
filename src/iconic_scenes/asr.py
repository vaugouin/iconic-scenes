"""Last resort when a copy has no subtitle track in the wanted language: local speech recognition.

faster-whisper runs on the CPU, offline, no API call. The audio has to be read from the NAS in full,
so this is slow (about 20 min to read a 4 GB file at ~3 MB/s, then the transcription)."""
import json
import subprocess
import wave

import numpy as np

from . import config

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MODEL = config.get("ICONIC_WHISPER_MODEL", "small")


def cues(part: dict, lang: str) -> list[dict]:
    """Speech segments of a copy as subtitle-like cues {start, end, text}, cached in work/asr/."""
    cache = config.WORK / "asr" / f"{part['id']}-{lang}-{MODEL}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    cache.parent.mkdir(parents=True, exist_ok=True)
    wav = cache.with_suffix(".wav")
    if not wav.exists():
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", part["file"], "-vn", "-sn",
                        "-ac", "1", "-ar", "16000", str(wav)], check=True, creationflags=NO_WINDOW, timeout=7200)
    with wave.open(str(wav)) as w:                    # decode ourselves: faster-whisper's PyAV decoder breaks on recent PyAV
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    from faster_whisper import WhisperModel          # heavy import, only when needed

    model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(audio, language=lang, vad_filter=True, beam_size=1,
                                   condition_on_previous_text=False)
    out = [dict(start=round(s.start, 2), end=round(s.end, 2), text=s.text.strip()) for s in segments if s.text.strip()]
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    wav.unlink()
    return out
