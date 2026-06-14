# Subs Manager AI — Plan

Self-hosted subtitle manager for a Jellyfin library. Tracks external `.srt` files and embedded MKV subtitle tracks per movie, supports upload, Whisper transcription, and translation via [llm-subtrans](https://github.com/machinewrapped/llm-subtrans).

> **Safety contract** — see §C. The app **never permanently deletes a user file**: deletions move to a quarantined trash dir; replacements keep timestamped `.bak` copies; video containers are protected absolutely. All destructive code MUST go through `app.core.safe_fs`.

---

## 1. Stack

| Layer | Choice | Reason |
|---|---|---|
| Backend | **Python 3.11 + FastAPI** | Whisper, llm-subtrans, ffmpeg bindings are all Python-native |
| DB | **SQLite + SQLModel** | Single-user, file-based, zero-ops |
| Job queue | **ARQ** (Redis) or **RQ** | Long-running Whisper/translate jobs need a worker outside HTTP; ARQ is async-native and matches FastAPI |
| Frontend | **React 18 + Vite + TypeScript + TanStack Query + Tailwind** | Standard, fast iteration, query lib handles polling for job progress |
| External bins | `ffmpeg`, `ffprobe`, `mkvmerge`, `mkvextract` (mkvtoolnix) | Probing/extraction/embedding |
| Whisper | `faster-whisper` (CTranslate2) | 4× speed of stock whisper, GPU optional |
| Translation | `llm-subtrans` as subprocess or imported lib | Provider-agnostic (OpenAI/Anthropic/local) |
| Container | Docker Compose (api, worker, redis, web) | Easy deploy beside Jellyfin |

---

## 2. Domain model

Library layout from sample tree: **one folder per movie**, named `Title (Year)`, containing one or more video files (different cuts/dubs/releases) plus sidecar subtitles, sometimes inside `subs/` or `alt/` subfolders. Files are often symlinks back to a `/raw/...` source. Junk files (`www.YTS.MX.jpg`) coexist.

So a `Movie` is the **folder**, and a folder can hold multiple `VideoFile` rows (e.g. `Superman (2025) - ESP.mkv` + `Superman (2025) - LAT.mkv`).

```
Movie                              -- one folder
  id, folder_path (abs), title, year
  scanned_at

VideoFile                          -- one per video inside the folder
  id, movie_id, path (abs), real_path (resolved if symlink), is_symlink
  filename, variant (suffix like "ESP"|"LAT"|"EN"|null), size, mtime
  hash (xxh64 of first+last MB of real_path)
  container (mkv/mp4/avi), duration, video_codec
  audio_tracks (jsonb)

ExternalSubtitle                   -- sidecar file (any depth ≤ 2 under folder)
  id, movie_id, path, real_path, is_symlink
  filename, rel_dir (""|"subs"|"alt")
  language (BCP-47, nullable until resolved)
  language_source: enum(filename|content|manual|unknown)
  format (srt/ass/vtt), forced: bool, sdh: bool
  custom_tag (e.g. "ai", "spanish.ai")  -- preserved free-form tail
  source: enum(manual|whisper|translated|extracted|preexisting)
  linked_video_file_id: nullable    -- if a specific variant
  parent_sub_id: nullable           -- for translated subs
  created_at

EmbeddedSubtitle                   -- mirror of MKV tracks; bound to VideoFile
  id, video_file_id, track_index, codec (srt/ass/pgs/vobsub)
  language, title, default: bool, forced: bool

Job
  id, type: enum(scan|transcribe|translate|extract|embed|upload|rename)
  status: enum(queued|running|done|failed|cancelled)
  movie_id, target_id (video_file or sub), params (jsonb)
  progress (0-100), log, error
  started_at, finished_at

LibraryRoot
  id, path, name, enabled

Setting (kv)
```

Canonical write naming = Jellyfin: `Title (Year).LANG[.forced|.sdh].srt`. Reads tolerate the messy patterns in §A.

---

## 3. Backend modules

```
app/
  api/            # FastAPI routers
    movies.py     # GET /movies, GET /movies/{id}
    subs.py       # POST /movies/{id}/subs (upload), DELETE, PATCH (rename/flag)
    jobs.py       # GET /jobs, POST /jobs/{type}, WS /jobs/stream
    library.py    # POST /scan, library roots CRUD
    settings.py
  core/
    config.py
    db.py
  scanner/
    walker.py     # walk roots, find video files
    sidecar.py    # match siblings by stem; parse lang/forced from suffix
    probe.py      # ffprobe → embedded tracks, audio info
    langdetect.py # fallback: read srt content if no lang in filename
  ops/
    whisper_op.py    # extract audio → faster-whisper → srt
    translate_op.py  # call llm-subtrans
    mkv_op.py        # mkvextract for pull, mkvmerge for embed
    upload_op.py     # validate srt → place beside movie with correct name
  workers/
    queue.py         # ARQ task definitions, progress reporting
  models.py
  main.py
```

### Key flows

**Scan** — walk `LibraryRoot.path` **one level deep**: each direct subfolder = a `Movie`. Parse `title` and `year` from folder name with regex `^(?P<title>.+?) \((?P<year>\d{4})\)$`.

Inside each movie folder:
1. Find video files at depth 0–2 (catches `alt/`). Resolve symlinks, store both raw and real path. Hash real path. ffprobe → duration, codec, audio + embedded sub tracks.
2. Variant detection: filename minus stem `Title (Year)` parsed for ` - XXX` or `.XXX` suffix → `VideoFile.variant`. Multiple variants ⇒ multiple `VideoFile` rows under one `Movie`.
3. Find subtitle files at depth 0–2 (`*.srt`, `*.ass`, `*.vtt`). Run `sub_name_parser` (see §A) → language, forced, sdh, custom_tag.
4. Skip junk: `*.jpg`, `*.png`, `*.nfo`, `Thumbs.db`, dotfiles.
5. Upsert by `real_path` so a symlinked twin does not double-insert.
6. Emit per-folder progress on the `Job`.

**Upload** — multipart POST. Validate it parses as SRT (use `pysrt` or `srt`). Determine target name from form field `language` + flags. Reject overwrite unless `force=true`. Write to disk beside movie. Insert row.

**Transcribe** — job extracts audio track (ffmpeg `-vn -ac 1 -ar 16000 -c:a pcm_s16le`) to temp wav, runs faster-whisper with configured model, writes srt with naming convention, inserts row with `source=whisper`. Stream progress from segment timestamps (`segment.end / duration`).

**Translate** — pick a source `ExternalSubtitle`, target language(s), shell out to `llm-subtrans` with provider config. On success insert child sub with `parent_sub_id` set, `source=translated`.

**Extract** (MKV) — `mkvextract tracks <file> <track_id>:<out.srt>` for the chosen embedded track. Insert as new `ExternalSubtitle` with `source=extracted`.

**Embed** (MKV) — `mkvmerge -o <new.mkv> <orig.mkv> --language 0:<lang> --track-name 0:<title> <sub.srt>`. Atomic replace original. Re-probe.

---

## 4. Frontend

```
web/src/
  pages/
    Library.tsx     # grid of movies with sub badges
    Movie.tsx       # detail: external + embedded tabs, action buttons
    Jobs.tsx        # live job table, progress bars, log drawer
    Settings.tsx    # roots, whisper, translator, naming
  components/
    SubBadge.tsx    # flag emoji + count
    LangPicker.tsx
    UploadDrop.tsx
    JobProgress.tsx
  api/              # generated openapi client (orval or hand-written)
```

- Library card: poster (optional, scrape from sibling `.jpg` or skip MVP), title, year, sub flags row, "needs subs" indicator if 0 external + 0 embedded.
- Movie page actions: **Upload**, **Transcribe (Whisper)**, **Translate from…**, **Extract embedded**, **Embed external into MKV**, **Delete sub**, **Mark forced/SDH**, **Rename to convention**.
- Job progress: WS or 2s poll on `/jobs/active`.
- Filters: missing-subs, has-language, source=whisper-only, etc.

---

## 5. Phases

| Phase | Deliverable | Validate |
|---|---|---|
| **0. Scaffold** | Compose stack up, hello-world API + web, SQLite migrations | `curl /health` ok, web loads |
| **1. Library + scan** | LibraryRoot CRUD, scanner, Movie list endpoint, library grid UI | Scan a real folder; counts match `find` |
| **2. External subs** | Sidecar detection, lang parse, fallback content detect, sub list per movie | Library with mixed `.en.srt` / `.es.forced.srt` parses correctly |
| **3. Upload + manage** | Upload endpoint, rename, delete, flag toggle | Round-trip from UI; file appears beside movie |
| **4. MKV embedded read** | ffprobe integration, embedded sub display | Track count matches `mkvinfo` |
| **5. MKV extract/embed** | Extract → srt sidecar; embed external → new mkv | Jellyfin picks them up |
| **6. Whisper** | Worker + transcribe op + progress | Generates en srt for a 5-min clip; quality sane |
| **7. Translate** | llm-subtrans wiring + provider config | en → es translation lands as child sub |
| **8. Polish** | fs watcher (watchdog), batch ops, dark mode, auth (basic/single user) | Drop a file in folder → appears in UI within 5s |

MVP = phases 0–3. Useful = 0–5. Full = 0–8.

---

## 6. Decisions (resolved)

| # | Decision | Implication |
|---|---|---|
| 1 | Docker Compose | Services: `api`, `worker`, `redis`, `web`. Mount library roots read-write. Mount `/raw` too because symlinks point there. |
| 2 | CPU-only | `faster-whisper` with `compute_type=int8`, default model `small` (good quality, ~1× realtime on modern CPU). Expose `tiny|base|small|medium` in settings. **VAD filter on** to skip silence. **VibeVoice is wrong tool** — see §B. |
| 3 | DeepSeek for translation | DeepSeek exposes OpenAI-compatible API. Configure llm-subtrans's OpenAI provider with `OPENAI_BASE_URL=https://api.deepseek.com/v1` + `OPENAI_API_KEY=<deepseek-key>` + model `deepseek-chat`. |
| 4 | No auth, LAN trust | Bind API to LAN IP only. No login UI. Document firewall expectation. |
| 5 | SQLite | Stays. Add WAL mode + index on `Movie.folder_path`, `VideoFile.real_path`, `ExternalSubtitle.real_path`. |
| 6 | Atomic MKV mux + 24h `.bak` | `mkvmerge -o <orig>.tmp.mkv ...` → `fsync` → rename → keep `<orig>.bak.mkv` 24h, cron in worker prunes. |

---

## 7. Risks

- **MKV mux corrupting files** → write to temp, fsync, atomic rename, keep `.bak` for 24h.
- **Whisper quality on noisy audio** → expose model size + VAD filter in settings; let user re-run.
- **llm-subtrans cost** → show token estimate before run; cache by source-sub-hash + target-lang.
- **Jellyfin filename pickiness** → enforce naming convention on write; lint button to fix existing.
- **Concurrent scan + upload** → file-lock per movie path.

---

## 8. First commit checklist

- [ ] `docker-compose.yml` (api, worker, redis, web; mounts: `/library`, `/raw`)
- [ ] `pyproject.toml` (fastapi, sqlmodel, arq, faster-whisper, pysrt, langdetect, watchdog, pymediainfo)
- [ ] `web/` Vite scaffold (React + TS + Tailwind + TanStack Query)
- [ ] `app/main.py` + `/health`
- [ ] Alembic baseline migration with the schema in §2
- [ ] `app/scanner/sub_name_parser.py` with the patterns in §A + unit tests for every example row
- [ ] `Makefile` (dev, scan, fmt, test)
- [ ] `.env.example` (`DEEPSEEK_API_KEY`, `LIBRARY_ROOTS`, `WHISPER_MODEL`, ...)

---

## §A. Subtitle filename patterns observed

Stem = movie folder name, e.g. `Suicide Club (2001)`.

| Pattern | Example from your tree | Parser output |
|---|---|---|
| `<stem>.srt` | `Shutter (2004).srt` | lang=**unknown** → fallback to content detect (`langdetect`); commonly English |
| `<stem>.<lang>.srt` | (canonical Jellyfin) | lang from suffix; matched against ISO-639 names + codes |
| `<stem>.<lang>.forced.srt` | canonical | forced=true |
| `<stem>.<word>.<word>.srt` | `Shutter (2004).spanish.ai.srt` | first word resolved as language if recognized (`spanish` → `es`); remainder → `custom_tag="ai"` |
| `<stem>_<lang>_<n>.srt` | `Suicide Club (2001)_es_1.srt` | lang=es, custom_tag=`alt-1` |
| `<n>_<Language>.srt` | `3_English.srt`, `4_Chinese.srt` | track-number prefix stripped; full-name lookup → `en`, `zh`. Lives in `subs/` |
| Inside `subs/` or `alt/` | all of above | record `rel_dir` for display, no other change |
| `www.YTS.MX.jpg` etc | — | **junk filter**, ignored |

Resolver order per file:
1. Strip `<stem>` or `<n>_` prefix.
2. Tokenize remaining stem on `.`, `_`, `-`.
3. For each token, lookup in (a) ISO-639-1 codes (`es`, `en`), (b) ISO-639-2 codes (`spa`, `eng`), (c) English names (`Spanish`, `Chinese`), (d) language aliases dict (`spanish→es`, `latino→es-419`, `castellano→es-ES`).
4. Flag tokens: `forced`, `sdh`, `cc`, `hi`, `default` set their respective bool.
5. Unknown tokens → joined into `custom_tag`.
6. If no language resolved: read first ~50 cues, run `langdetect`, mark `language_source=content`.
7. UI lets user override; manual override sets `language_source=manual` and is sticky across rescans.

Write side (renames, new subs, Whisper output, translations) always emits canonical Jellyfin form.

---

## §B. Note on VibeVoice

**VibeVoice is a TTS (text-to-speech) model from Microsoft Research** — it generates *audio from text*, the opposite direction of what subtitle generation needs. For a subtitle workflow we need **STT (speech-to-text)**, which is what Whisper does.

VibeVoice would only be useful here if you wanted a *separate* feature like "read these subtitles aloud as a voice-over" — niche, and not part of this project.

For STT on CPU, the realistic options are:

| Tool | Notes |
|---|---|
| **`faster-whisper`** (recommended) | Whisper reimplemented on CTranslate2. 4× faster than openai-whisper on CPU. `int8` quant + `small` model handles a 2h film in ~1–2h CPU time. |
| `whisper.cpp` | C++ port, also fast, can be called as subprocess. Worth it if Python deps are heavy in your container. |
| `openai-whisper` (reference) | Slow on CPU. Avoid. |

Stick with `faster-whisper`. Expose model size + language hint + VAD on/off in settings.

---

## §C. Safety invariants (data-loss prevention)

Implemented in `app/core/safe_fs.py` and `app/core/policy.py`. **Every** future destructive code path must comply.

### Hard rules

1. **Video files are sacred.** No code path may delete or overwrite a file with extension in `VIDEO_EXTS` (`.mkv .mp4 .avi .m4v .mov .webm .ts`) **except** the MKV mux flow, which goes through `replace_with_backup()` and keeps the original as `.bak.<ts>`.
2. **No raw `unlink`** for any path inside a library root. Use `safe_fs.trash(path)` — this *moves* the file to `<DATA_DIR>/trash/<ts>_<basename>` instead of deleting. Restoring is a `mv` away.
3. **No raw `open(path, "wb")` for replacements.** Use `safe_fs.atomic_write(path, data, replace=True)`. It writes to `.tmp.<pid>.<ts>`, fsyncs, then renames — torn writes impossible.
4. **No silent overwrites on upload.** Default is reject if target exists. `force=true` routes the existing file through `trash()` first, then writes.
5. **Path containment.** `ensure_within(path)` is called by every primitive; paths outside library roots / data dir raise `PathEscapeError`. Symlink targets are checked too — a symlink in the library that points outside is treated as outside.
6. **Preexisting subs are read-only.** `policy.PROTECTED_SUB_SOURCES = {preexisting}`. The DELETE endpoint refuses these with `PolicyViolation`. Only subs the app generated (`whisper`, `translated`, `extracted`, `manual`) may be trashed.
7. **Backups expire, originals don't.** `prune_backups()` removes `.bak.<ts>` files older than 24h. Trash is **never** auto-pruned in phase 0–8 — user clears it manually.

### Backup retention table

| Operation | What gets kept | Where | Auto-pruned? |
|---|---|---|---|
| `trash(sub)` | the sub file | `$DATA_DIR/trash/<ts>_<name>` | No. User-managed. |
| `replace_with_backup(mkv, new)` | original mkv | `<dir>/<name>.bak.<ts>` | Yes — 24h, by worker. |
| `atomic_write(replace=True)` over a sub | nothing | — | The replaced sub is trashed *first* by the calling endpoint, not by atomic_write. |

### Refusal matrix (enforced by tests)

| Caller wants to | Path is | Result |
|---|---|---|
| atomic_write | inside roots, non-video, doesn't exist | OK, written |
| atomic_write | inside roots, non-video, exists, replace=False | `DestinationExistsError` |
| atomic_write | inside roots, **video** | `ProtectedFileError` |
| atomic_write | outside roots | `PathEscapeError` |
| trash | inside roots, non-video | OK, moved to trash |
| trash | inside roots, **video** | `ProtectedFileError` |
| trash | outside roots | `PathEscapeError` |
| trash | symlink → outside | `PathEscapeError` |
| delete preexisting sub via API | — | `PolicyViolation` (HTTP 403) |
| delete app-owned sub via API | — | `safe_fs.trash()` |

If a future feature needs an exception, the rule is: **add an explicit, named, tested escape hatch** (like `replace_with_backup` for MKV mux). Never reach around the primitives with raw `os` calls.
