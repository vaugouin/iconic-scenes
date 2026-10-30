"""Frame extraction with ffmpeg around a time span (accurate input seek, HDR tone-mapped to SDR)."""
import json
import shutil
import subprocess
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
           "zscale=t=bt709:m=bt709:r=tv,format=yuv420p")


def probe(video: str) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,color_transfer,r_frame_rate:format=duration", "-of", "json", video],
                         capture_output=True, text=True, check=True, creationflags=NO_WINDOW, timeout=120)
    data = json.loads(out.stdout)
    st = data["streams"][0]
    return dict(width=st.get("width"), height=st.get("height"), hdr=st.get("color_transfer") in ("smpte2084", "arib-std-b67"),
                duration=float(data.get("format", {}).get("duration", 0) or 0))


def extract(video: str, start: float, end: float, out: Path, fps: float = 6, hdr: bool = False) -> list[tuple[float, Path]]:
    """Frames from `start` to `end` (seconds) at `fps`, scaled to 1920 wide at most, as PNG files."""
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    vf = (TONEMAP + "," if hdr else "") + f"fps={fps},scale='min(1920,iw)':-2"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{max(0, start):.3f}", "-i", video,
                    "-t", f"{end - start:.3f}", "-an", "-sn", "-vf", vf, "-y", str(out / "f%04d.png")],
                   check=True, creationflags=NO_WINDOW, timeout=900)
    files = sorted(out.glob("f*.png"))
    return [(max(0, start) + i / fps, f) for i, f in enumerate(files)]
