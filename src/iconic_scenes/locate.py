"""Find a line in a list of subtitle cues by fuzzy alignment (rapidfuzz), no language model."""
import re
import unicodedata

from rapidfuzz import fuzz


def normalize(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("œ", "oe")
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)|♪", " ", text)            # sound descriptions, music
    text = re.sub(r"(^|\s)-\s*", " ", text)                          # dialogue dashes
    text = re.sub(r"\b[A-Z][A-Z .'-]{1,20}:\s", " ", text)            # SDH speaker labels
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9']+", " ", text).replace("'", "")
    return re.sub(r"\s+", " ", text).strip()


def find(quote: str, cues: list[dict], occurrence: str = "") -> dict | None:
    """Best alignment of `quote` over the concatenated cues.

    When the line is said several times (score within 2 points of the best), `occurrence` picks one:
    "" or "first", "last", or a 1-based number. Returns the score (0-100), the matched cues and their time span."""
    pieces, owner, pos = [], [], 0
    for i, cue in enumerate(cues):
        t = normalize(cue["text"])
        if not t:
            continue
        pieces.append(t)
        owner.extend([i] * (len(t) + 1))
        pos += len(t) + 1
    full = " ".join(pieces)
    q = normalize(quote)
    if not q or not full:
        return None
    found = []
    # Slide over overlapping chunks so long films stay fast and every occurrence competes.
    width = max(len(q) * 4, 400)
    step = width // 2
    for start in range(0, max(1, len(full) - len(q) + 1), step):
        chunk = full[start:start + width + len(q)]
        al = fuzz.partial_ratio_alignment(q, chunk)
        if al and al.score > 0:
            found.append((al.score, start + al.dest_start, start + al.dest_end))
    if not found:
        return None
    top = max(f[0] for f in found)
    hits = []
    for f in sorted((f for f in found if f[0] >= top - 2), key=lambda f: f[1]):
        if hits and f[1] - hits[-1][1] < len(q):           # the same occurrence seen from two overlapping chunks
            if f[0] > hits[-1][0]:
                hits[-1] = f
            continue
        hits.append(f)
    if occurrence == "last":
        pick = hits[-1]
    elif occurrence.isdigit():
        pick = hits[min(int(occurrence), len(hits)) - 1]
    else:
        pick = max(hits, key=lambda f: f[0]) if not occurrence else hits[0]
    score, a, b = pick
    while a < b and full[a] == " ":                       # a leading space belongs to the previous cue
        a += 1
    while b > a and full[b - 1] == " ":
        b -= 1
    first, last = owner[min(a, len(owner) - 1)], owner[max(a, min(b - 1, len(owner) - 1))]
    hit = cues[first:last + 1]
    return dict(score=round(score, 1), first=first, last=last, start=hit[0]["start"], end=hit[-1]["end"],
                text=" / ".join(c["text"] for c in hit), matched=full[a:b], occurrences=len(hits))
