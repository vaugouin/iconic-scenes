"""Settings: Plex access is shared with open-credits, the work folder is local."""
import os
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
SITE = ROOT / "site"
WORK = Path(os.environ.get("ICONIC_WORK", ROOT / "work"))
MODELS = ROOT / "models"
OC_DIR = Path(os.path.expandvars(r"%LOCALAPPDATA%\opencredits"))
OC_ENV = Path(os.environ.get("ICONIC_PLEX_ENV", OC_DIR / "opencredits.env"))
OC_INDEX = Path(os.environ.get("ICONIC_PLEX_INDEX", OC_DIR / "opencredits.sqlite"))


@cache
def _env_file() -> dict:
    values = {}
    if OC_ENV.exists():
        for line in OC_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get(key: str, default: str = "") -> str:
    return os.environ.get(key) or _env_file().get(key, default)


def path_map() -> list[tuple[str, str]]:
    """OC_PATH_MAP: 'plex_prefix=local_prefix;...', e.g. /volume1/sharing=T:"""
    pairs = []
    for item in get("OC_PATH_MAP", "/volume1/sharing=T:").split(";"):
        if "=" in item:
            plex_prefix, local_prefix = item.split("=", 1)
            pairs.append((plex_prefix.rstrip("/"), local_prefix.rstrip("/")))
    return pairs
