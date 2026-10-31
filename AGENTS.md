# iconic-scenes

## Purpose

Famous movie line (`data/quotes.csv`) to best still from the Plex library (drive `T:`), rendered as `site/index.html`. No LLM, no token cost: keep it that way. What it does, status and commands: `README.md`; module roles: each module's docstring under `src/iconic_scenes/`. Created 2026-10-29 by Nestor at Philippe's request.

## Repository and versioning

- Public on GitHub: <https://github.com/vaugouin/iconic-scenes>, code under MIT (`LICENSE`). `README.md` is the public description, in English, no em dashes.
- The version lives in `pyproject.toml` and `src/iconic_scenes/__init__.py`: bump both (then `uv lock`) in every commit.
- Never commit stills (`site/img/`, frames of copyrighted films) or `work/`.
- Listed in the ecosystem docs: the profile README (`~/Code/vaugouin/README.md`, "Other projects"), the About page (`~/Code/tmdb-front/lib/about.inc.php`) and `tmdb-front/AGENTS.md`, and the roster `~/Nestor/projets/t2s-backlog/topics/related-repositories.txt`. Update them if the repo is renamed or archived.

## Dependencies on other repos

- **open-credits**: Plex URL, token and path map are read from `%LOCALAPPDATA%\opencredits\opencredits.env` (`PLEX_SERVER_URL`, `PLEX_TOKEN`, `OC_PATH_MAP`), and the TMDb-id-to-Plex index from `%LOCALAPPDATA%\opencredits\opencredits.sqlite` (table `plex_movie`, opened read-only). Override with `ICONIC_PLEX_ENV` and `ICONIC_PLEX_INDEX`. Never print or commit the token.

## Pitfalls (measured)

- **T: reads at about 3 MB/s** from this PC (2026-10-29, same through Plex HTTP). Reading a whole file (embedded subtitle extraction, ASR audio) takes 15 to 30 min for 3 to 5 GB; a frame window reads only a few dozen MB. Hence the order of `pipeline.tracks()`: sidecar files first, embedded tracks of the smallest copies last, capped by `ICONIC_EMBEDDED_MAX`.
- **Plex serves only sidecar subtitles** over `/library/streams/{id}` (embedded tracks answer 501).
- **Plex is read-only for this tool.** Fetching OpenSubtitles through Plex requires attaching the result to a copy (`PUT`), which changes the shared library: ask Philippe before adding that route.
- **Subtitle and frames must come from the same copy** (cut, PAL speed-up, offset differ between copies): `run_one` extracts frames from the part that owns the matched track.
- **Never glob T:** (HDFilms, 4KFilms hold thousands of files): go through the Plex index.
- **Dolby Vision profile 5** decodes with wrong colours; `part_order` puts DV and HDR copies last. HDR10 is tone-mapped with zscale + hable.
- **Plex metadata calls sometimes time out**: three tries, every answer cached in `work/plex/`.
- **Dark edges are not bars**: `score.active_area` crops only rows or columns black end to end, symmetrically (the *Taxi Driver* mirror shot lost its dark left side otherwise).
- **A line said several times**: the `occurrence` column of `quotes.csv` picks it (`last`, or a 1-based number among matches within 2 points of the best); e.g. *Streetcar* is `3`.
- **faster-whisper cannot decode audio with recent PyAV** (`metadata_errors` keyword): `asr.py` reads the WAV with `wave` and passes the samples, and keeps the WAV until transcription succeeds so a crash does not cost a second 20-minute read.
- **A "Forced" track holds only foreign-language lines**, so `candidates()` ranks forced tracks last (*La Grande Vadrouille*, 2026-10-30).
- **Sidecar-only runs reuse embedded tracks already extracted** (`subtitles.cached`): rerun freely after tuning the scoring.
- Do not kill ffmpeg by image name (`taskkill /IM ffmpeg.exe`): other jobs on the PC use it. Stop the background task that started it.
