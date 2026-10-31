# iconic-scenes

## Purpose

Famous movie line (`data/quotes.csv`) to best still from the Plex library (drive `T:`), rendered as `site/index.html`. No LLM, no token cost: keep it that way. What it does, status and commands: `README.md`; module roles: each module's docstring under `src/iconic_scenes/`. Created 2026-10-29 by Nestor at Philippe's request.

## Repository and versioning

- Public on GitHub: <https://github.com/vaugouin/iconic-scenes>, code under MIT (`LICENSE`). `README.md` is the public description, in English, no em dashes.
- The version lives in `pyproject.toml` and `src/iconic_scenes/__init__.py`: bump both (then `uv lock`) in every commit.
- Never commit stills (`site/img/`, frames of copyrighted films) or `work/`.
- Listed in the ecosystem docs: the profile README (`~/Code/vaugouin/README.md`, "Other projects"), the About page (`~/Code/tmdb-front/lib/about.inc.php`) and `tmdb-front/AGENTS.md`, and the roster `~/Nestor/projets/t2s-backlog/topics/related-repositories.txt`. Update them if the repo is renamed or archived.

## Export and tmdb-front

- `export.py` writes `data/iconic-scenes.csv` (one row per line of `quotes.csv`, everything the page shows) and `data/iconic-scenes.sql` (upsert into `T_WC_ICONIC_SCENE`, DDL in `doc/sql/T_WC_ICONIC_SCENE.sql`). `report.py` renders `site/index.html` from the same rows, so the CSV is enough to rebuild the page.
- tmdb-front `iconic-scenes.php` (`lib/iconic-scenes.inc.php`) renders the same page from the table, in the private folders only. Its stills come from `~/docker/shared_data/iconic-scenes/` on the VPS, mounted read-only at `/iconic-scenes/`; copy `site/img/*.jpg` there, never into git.
- The DDL and the load run through route 2 (Philippe, `runsqlvaugouindb.sh`): the agent account cannot write to this table.
- Subtitle text goes through `export.clean()`: some sidecar files carry NUL bytes, and the MariaDB client stops the load on the first one (2026-10-31, *Some Like It Hot*).

## Dependencies on other repos

- **open-credits**: Plex URL, token and path map are read from `%LOCALAPPDATA%\opencredits\opencredits.env` (`PLEX_SERVER_URL`, `PLEX_TOKEN`, `OC_PATH_MAP`), and the TMDb-id-to-Plex index from `%LOCALAPPDATA%\opencredits\opencredits.sqlite` (table `plex_movie`, opened read-only). Override with `ICONIC_PLEX_ENV` and `ICONIC_PLEX_INDEX`. Never print or commit the token.

## Pitfalls (measured)

- **T: throughput varies tenfold with the NAS load**: 3 MB/s on 2026-10-29, 30 MB/s for one reader and about 60 MB/s for three on 2026-10-31 (a 2.7 GB copy demuxed in 46 s). Measure before concluding (`dd if=<file> of=/dev/null bs=4M count=50 skip=100`). Reading a whole file (embedded subtitle extraction, ASR audio) depends on it; a frame window reads only a few dozen MB. `pipeline.tracks()` tries sidecar files first, then embedded tracks smallest copy first, capped by `ICONIC_EMBEDDED_MAX` (30 GB, skips the 40 to 130 GB remuxes). For many lines, run three `run <ids>` processes in parallel.
- **Plex serves only sidecar subtitles** over `/library/streams/{id}` (embedded tracks answer 501), and `/video/:/transcode/universal/subtitles` returns nothing without a playback session (2026-10-31): no server-side extraction.
- **One film can be several Plex items** (unmerged copies): `run_one` pools the copies of every item with the TMDb id (*Star Wars*: DVD rip in one, 1080p in another). When the index title differs ("Star Wars: Episode V - ..."), set `tmdb_id` in `quotes.csv`.
- **Speech recognition** uses the audio track in the line's language (`asr.audio_index`; dubbed copies list French first). Whole-film segments can span 40 s or more, so the best match (or, below 80, the five best from `locate.windows`) gets a second pass (`pipeline._word_pass`, `asr.words`: input seek, beam 5, word timestamps) that sharpens the times and confirms or rejects the line. Transcribe each segment alone: one window over a 132 s and a 41 s segment lost *Le Corniaud* (78), the 41 s one alone gave 95. *Le Mépris* was the third-best coarse window. The VAD filter can drop speech over sea or music noise (*Pierrot le fou*).
- **A track may leave the first utterance unsubtitled** (*Citizen Kane*'s dying "Rosebud", missing from three of five English tracks): `occurrence=first` reads every track and keeps the earliest hit.
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
