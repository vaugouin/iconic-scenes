# iconic-scenes

## Purpose

From a list of famous movie lines (`data/quotes.csv`), find each line in the film's subtitles on the Plex library (drive `T:`), pull the frames of that moment with ffmpeg, and keep the best still (sharp, well framed, well exposed). The result is a static page, `site/index.html`, with the stills in `site/img/`.

**No LLM, no token cost.** The line is found by fuzzy alignment (rapidfuzz) and the still is chosen by classical computer vision (OpenCV). The only model is the YuNet face detector (ONNX, 230 KB), plus faster-whisper for local speech recognition as a last resort.

Created 2026-10-29 by Nestor at Philippe's request.

## Stack and layout

Python 3.12, uv. ffmpeg and ffprobe on PATH (the build needs `libzimg` to tone-map HDR).

```
data/quotes.csv          the lines: id, tmdb_id (optional, when the title does not match the Plex index), title, year, lang (en|fr), who, quote
src/iconic_scenes/
  config.py              paths and settings; Plex access read from open-credits' env file
  plex.py                Plex HTTP API (read-only) + lookup in the open-credits SQLite index (tmdb id -> rating key)
  subtitles.py           subtitle tracks of a copy: sidecar download from Plex, or ffmpeg extraction of an embedded track; pysubs2 parsing
  locate.py              normalisation + rapidfuzz partial_ratio_alignment over the concatenated cues
  asr.py                 faster-whisper fallback (CPU, offline) when no subtitle track exists
  frames.py              ffprobe, ffmpeg extraction around the matched span (accurate input seek, HDR tone-mapped)
  score.py               still selection: Laplacian + Tenengrad sharpness, YuNet faces (size, placement, focus), exposure, shot-cut distance
  pipeline.py            one quote end to end, results cached in work/results/<id>.json
  report.py              site/index.html
models/                  YuNet ONNX (gitignored, download below)
work/                    caches: Plex metadata, subtitles, ASR, results (gitignored)
site/                    index.html (versioned) and img/ (gitignored: film stills)
```

## Commands

```bash
uv sync
curl -sSL -o models/face_detection_yunet_2023mar.onnx https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
uv run iconic-scenes run --sidecar-only      # fast pass: only subtitle files Plex serves over HTTP
uv run iconic-scenes run                     # adds embedded tracks of copies under ICONIC_EMBEDDED_MAX bytes (default 4e9)
uv run iconic-scenes run tontons-flingueurs --speech   # local speech recognition when no track exists
uv run iconic-scenes run taxi-driver --force # redo one quote
uv run iconic-scenes report                  # rewrite site/index.html
```

## Dependencies on other repos

- **open-credits**: Plex URL, token and path map are read from `%LOCALAPPDATA%\opencredits\opencredits.env` (`PLEX_SERVER_URL`, `PLEX_TOKEN`, `OC_PATH_MAP`), and the TMDb-id-to-Plex index from `%LOCALAPPDATA%\opencredits\opencredits.sqlite` (table `plex_movie`, opened read-only). Override with `ICONIC_PLEX_ENV` and `ICONIC_PLEX_INDEX`. Never print or commit the token.

## State (2026-10-30)

118 candidate lines in `quotes.csv` (94 English, 24 French): **59 stills**. 45 come from Plex sidecar files, 13 from embedded tracks of copies under 4 GB, 1 from speech recognition (*Les Tontons flingueurs*, whose copies carry no subtitles at all). The failures are listed at the bottom of the page; most are films whose only text track is embedded in a copy above 4 GB, and French films with no French subtitles (French audio does not need any).

## Pitfalls (measured)

- **T: reads at about 3 MB/s** from this PC (measured 2026-10-29, same through the Plex HTTP download). Anything that reads a whole file is slow: extracting an embedded subtitle track demuxes the entire mkv (15 to 30 min for 3 to 5 GB), and so does audio extraction for ASR. Hence the order of `pipeline.tracks()`: sidecar files first (one HTTP call), embedded tracks of the smallest copies last, capped by `ICONIC_EMBEDDED_MAX`. A frame window of a few seconds only reads a few dozen MB.
- **Plex serves only sidecar subtitles** over `/library/streams/{id}` (embedded tracks answer 501).
- **Plex is read-only for this tool.** Plex can search OpenSubtitles itself (`GET /library/metadata/{key}/subtitles?language=fr`), but a result can only be downloaded once attached to a copy (`PUT`), which changes the shared library: not done. Ask Philippe before adding that route.
- **Subtitle and frames must come from the same copy**: two copies of one film can differ by cut, frame rate (PAL speed-up) or offset. `run_one` extracts frames from the part that owns the matched track.
- **Listing a big folder on T: is very slow** (HDFilms, 4KFilms hold thousands of files): go through the Plex index, never glob T:.
- **Dolby Vision profile 5** copies decode with wrong colours; `part_order` puts DV and HDR copies last. HDR10 is tone-mapped with zscale + hable.
- **Plex metadata calls sometimes time out**: three tries, and every answer is cached in `work/plex/`.
- **Dark edges are not bars**: `score.active_area` crops only rows or columns that are black end to end, symmetrically (a first version cut the dark left side of the *Taxi Driver* mirror shot).
- **A line said several times**: the `occurrence` column of `quotes.csv` picks it (`last`, or a 1-based number among the matches within 2 points of the best). *Casablanca* is `last` (the airport), *Streetcar* is `3` ("Hey, Stella!" is said six times; the third is the scream in the courtyard).
- **faster-whisper cannot decode audio with recent PyAV** (`open() got an unexpected keyword argument 'metadata_errors'`): `asr.py` reads the WAV with the `wave` module and passes the samples. The WAV is kept until the transcription succeeds, so a crash does not cost a second 20-minute read.
- **A "Forced" track holds only the foreign-language lines**: it cannot carry a famous line in the film's own language (*La Grande Vadrouille*, 2026-10-30). `candidates()` ranks forced tracks last for that reason.
- **Sidecar-only runs reuse embedded tracks already extracted** (`subtitles.cached`), so a rerun after tuning the scoring never reads a whole file again.
- Do not kill ffmpeg by image name (`taskkill /IM ffmpeg.exe`): other jobs on the PC use it. Stop the background task that started it.
