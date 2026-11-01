# iconic-scenes

From a famous movie line to the best still of that moment, without a language model.

Give it a line ("You talkin' to me?", *Taxi Driver*; "Il connaît pas Raoul", *Les Tontons flingueurs*) and the film it comes from. It finds the line in the film's subtitles on a Plex library, extracts the frames of the few seconds around it, and keeps the single best still: sharp, well framed, well exposed, ideally on the face of the person speaking. The result is a static web page with one card per line: the still, the line, the film, the timecode and the matched subtitle text.

## Why no LLM

Every step is done by existing software and classical algorithms, at no token cost:

- **Finding the line**: fuzzy alignment with [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) over the concatenated subtitle cues, so a line that is paraphrased, split across two cues or written differently in the subtitles is still found. When a line is said several times, a column of the list picks the occurrence.
- **Getting the subtitles**: sidecar subtitle files served by the Plex HTTP API first, then embedded text tracks extracted with ffmpeg, and as a last resort local speech recognition with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on the CPU, for copies that carry no subtitles at all.
- **Extracting the frames**: ffmpeg with an accurate seek on the matched span, from the same copy as the subtitles (two copies of a film can differ by cut, frame rate or offset), HDR copies tone-mapped to SDR.
- **Choosing the still**: OpenCV. Sharpness (Laplacian variance and Tenengrad), faces found by the [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) detector (size, placement on the thirds, focus on the face), exposure and contrast, distance from a shot cut, and a bonus for frames during the line itself. Letterbox bars are cropped.

## Status

Version 0.1, November 2026. Of 242 candidate lines (208 in English, 34 in French), 238 have a still: 83 from Plex sidecar files, 119 from embedded tracks, 36 from local speech recognition (films with no subtitles in the line's language, or image-only subtitles). Of the four lines left, listed at the bottom of the page, three are not in the film as written (a misremembered wording, or a one-word exclamation that speech recognition writes as "OK"), and one is matched in Plex to the wrong film (*Anchorman*, filed under its companion film *Wake Up, Ron Burgundy*).

Known limit: in a shot and reverse shot, nothing tells which of the two faces is speaking, so a few stills show the listener rather than the speaker.

## Usage

Requires Python 3.12 with [uv](https://docs.astral.sh/uv/), ffmpeg and ffprobe on the PATH (built with `libzimg` for HDR tone-mapping), and a Plex server. The Plex URL, token and path map, and the index that maps TMDb IDs to Plex items, are read from the configuration of [open-credits](https://github.com/vaugouin/open-credits); see [AGENTS.md](AGENTS.md) for the details.

```bash
uv sync
curl -sSL -o models/face_detection_yunet_2023mar.onnx https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
uv run iconic-scenes run --sidecar-only          # fast pass: subtitle files Plex serves directly
uv run iconic-scenes run                         # adds the embedded tracks of smaller copies
uv run iconic-scenes run tontons-flingueurs --speech   # speech recognition when no track exists
uv run iconic-scenes report                      # rewrite site/index.html
```

The lines live in [`data/quotes.csv`](data/quotes.csv): an id, the title and year (or a TMDb ID when the title does not match), the language, who says it, the line, and optionally which occurrence to take.

Plex is only read, never modified.

## Stills and copyright

The stills are frames of copyrighted films. They are produced locally in `site/img/` and are not part of this repository, so the committed `site/index.html` shows the page structure with missing images.

## Licence

Code under the MIT licence, see [LICENSE](LICENSE).
