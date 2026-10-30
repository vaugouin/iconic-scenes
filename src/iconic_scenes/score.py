"""Pick the best still among candidate frames: sharp, well exposed, faces in focus, away from cuts.

Classical computer vision only: Laplacian variance, Tenengrad, histogram shot-change, YuNet face detector."""
from functools import cache

import cv2
import numpy as np

from . import config

MODEL = config.MODELS / "face_detection_yunet_2023mar.onnx"


@cache
def _detector():
    return cv2.FaceDetectorYN.create(str(MODEL), "", (320, 320), 0.7, 0.3, 50)


def active_area(img: np.ndarray) -> tuple[int, int, int, int]:
    """Bounding box (x, y, w, h) without letterbox or pillarbox bars.

    A bar is a run of rows (or columns) that are black end to end, not merely dark; bars are
    symmetric, so the thinner side decides, which keeps a dark edge of the picture from being cut."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    def bar(profile: np.ndarray) -> int:
        dark = profile < 24
        lead = int(np.argmin(dark)) if not dark.all() else len(dark)
        trail = int(np.argmin(dark[::-1])) if not dark.all() else len(dark)
        side = min(lead, trail)
        return side if 4 <= side < len(dark) * 0.3 else 0

    top = bar(np.percentile(gray, 99, axis=1))
    left = bar(np.percentile(gray, 99, axis=0))
    h, w = gray.shape
    return left, top, w - 2 * left, h - 2 * top


def sharpness(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def tenengrad(gray: np.ndarray) -> float:
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    return float(np.mean(gx * gx + gy * gy))


def hist(img: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(cv2.resize(img, (160, 90)), cv2.COLOR_BGR2HSV)
    h = cv2.calcHist([hsv], [0, 1], None, [32, 16], [0, 180, 0, 256])
    return cv2.normalize(h, h).flatten()


def measure(path) -> dict:
    img = cv2.imread(str(path))
    x, y, w, h = active_area(img)
    crop = img[y:y + h, x:x + w]
    scale = 960 / crop.shape[1]
    small = cv2.resize(crop, (960, int(crop.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    det = _detector()
    det.setInputSize((small.shape[1], small.shape[0]))
    _, faces = det.detect(small)
    face_list = []
    for f in faces if faces is not None else []:
        fx, fy, fw, fh, conf = float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[-1])
        x0, y0 = max(0, int(fx)), max(0, int(fy))
        roi = gray[y0:int(fy + fh), x0:int(fx + fw)]
        if roi.size < 400:
            continue
        inside = fx >= 0 and fy >= 0 and fx + fw <= small.shape[1] and fy + fh <= small.shape[0]
        face_list.append(dict(conf=conf, area=fw * fh / (small.shape[0] * small.shape[1]),
                              cx=(fx + fw / 2) / small.shape[1], cy=(fy + fh / 2) / small.shape[0],
                              sharp=sharpness(cv2.resize(roi, (128, 128))), inside=inside))
    return dict(crop=(x, y, w, h), sharp=sharpness(gray), teng=tenengrad(gray), mean=float(gray.mean()),
                std=float(gray.std()), clip=float(((gray < 8) | (gray > 247)).mean()), faces=face_list, hist=hist(small))


def _rank(values: list[float]) -> np.ndarray:
    """Percentile rank in [0, 1] within the candidate set."""
    v = np.asarray(values, dtype=float)
    if len(v) < 2:
        return np.ones_like(v)
    return v.argsort().argsort() / (len(v) - 1)


def face_score(faces: list[dict], ref_sharp: float) -> float:
    """0..1: a confident, in-focus face of a readable size, whole, near a third or the centre line."""
    best = 0.0
    for f in faces:
        size = min(f["area"] / 0.02, 1.0) * (1.0 if f["area"] < 0.30 else 0.6)
        place = 1.0 - min(abs(f["cy"] - 0.38) / 0.4, 1.0) * 0.5
        thirds = min(abs(f["cx"] - t) for t in (1 / 3, 0.5, 2 / 3))
        place *= 1.0 - min(thirds / 0.3, 1.0) * 0.4
        focus = min(f["sharp"] / max(ref_sharp, 1e-6), 1.0)
        s = f["conf"] * (0.35 * size + 0.25 * place + 0.40 * focus) * (1.0 if f["inside"] else 0.6)
        best = max(best, s)
    return best


def choose(frames: list[tuple[float, object]], span: tuple[float, float]) -> tuple[int, list[dict]]:
    """Score every frame; return the index of the best one and the per-frame details."""
    m = [measure(p) for _, p in frames]
    n = len(m)
    # Shot changes: a big histogram jump between neighbours. Frames next to a cut are often blended or blurred.
    diff = [0.0] + [1 - float(cv2.compareHist(m[i - 1]["hist"], m[i]["hist"], cv2.HISTCMP_CORREL)) for i in range(1, n)]
    cut = [d > 0.35 for d in diff]
    near_cut = [cut[i] or (i + 1 < n and cut[i + 1]) for i in range(n)]
    sharp_r = 0.5 * _rank([x["sharp"] for x in m]) + 0.5 * _rank([x["teng"] for x in m])
    face_sharps = sorted(f["sharp"] for x in m for f in x["faces"])
    ref = face_sharps[int(len(face_sharps) * 0.9)] if face_sharps else 1.0
    a, b = span
    details = []
    for i, ((t, _), x) in enumerate(zip(frames, m)):
        exposure = 1.0 - min(abs(x["mean"] - 110) / 110, 1.0) * 0.6 - min(x["clip"] * 3, 0.4)
        contrast = min(x["std"] / 55, 1.0)
        fs = face_score(x["faces"], ref)
        during = 1.0 if a <= t <= b else max(0.0, 1.0 - min(abs(t - a), abs(t - b)) / 1.5)
        total = (0.30 * sharp_r[i] + 0.35 * fs + 0.10 * exposure + 0.10 * contrast + 0.15 * during
                 - (0.25 if near_cut[i] else 0.0) - (0.4 if x["mean"] < 25 else 0.0))
        details.append(dict(t=round(t, 3), total=round(float(total), 4), sharp=round(x["sharp"], 1),
                            face=round(fs, 3), faces=len(x["faces"]), exposure=round(exposure, 3),
                            during=round(during, 2), near_cut=near_cut[i], crop=x["crop"]))
    best = max(range(n), key=lambda i: details[i]["total"])
    return best, details
