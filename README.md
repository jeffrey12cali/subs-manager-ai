# subs-manager-ai

Self-hosted subtitle manager for a Jellyfin library. Scans movie folders for
external and embedded subtitle tracks, and provides a web UI to upload, rename,
extract from MKV containers, transcribe with Whisper, and translate with
DeepSeek.

---

## Features

- **Named libraries** — define movie and series libraries in `.env`; switch
  between them in the UI.
- **Library scan** — walks Jellyfin-style `Title (Year)/` movie folders and
  series folders, parses sidecar subtitle filenames (30+ naming patterns),
  probes MKV embedded tracks via ffprobe.
- **Series browsing** — a series page lists seasons and episodes. Clicking an
  episode opens the same detail view and subtitle actions as a movie.
- **Upload & manage** — upload SRT/ASS/VTT files, set language/flags, rename
  to Jellyfin convention, delete (moves to trash, never permanent).
- **MKV extract** — pull an embedded subtitle track out as a sidecar `.srt`.
- **MKV embed** — add an external subtitle as a new embedded track; original
  MKV is backed up for 24 h.
- **Whisper transcription** — CPU transcription via `faster-whisper`
  (`small`/`int8` by default, ~1–2 h per 2-h film on a modern CPU).
- **AI translation** — translate any subtitle to another language via DeepSeek
  (OpenAI-compatible API), batched in 50-line chunks with retry.
- **Job queue** — long-running operations run in an ARQ/Redis worker; progress
  visible in the Jobs page.

---

## Requirements

**Docker Compose path (recommended)**

- Docker Engine 24+ and Docker Compose v2
- The host path to your Jellyfin movie library (and, if the library uses
  symlinks with absolute targets, the tree those targets live in)

**Local development path**

- Python 3.11+ and [`uv`](https://github.com/astral-sh/uv)
- Node 20+ and npm
- `ffmpeg` and `mkvtoolnix` installed on the host

---

## Quick start (Docker Compose)

### 1. Clone and configure

```bash
git clone https://github.com/your-user/subs-manager-ai
cd subs-manager-ai
cp .env.example .env
```

Setting up the library takes **two** coordinated pieces — the host mount (in
`docker-compose.yml`) and the scan roots (in `.env`).

**1. Mount your library into the container** — edit the `volumes:` of both the
`api` and `worker` services in `docker-compose.yml`. Mount the top of your
media tree at the **identical absolute path** inside the container:

```yaml
    volumes:
      - ./api:/app
      - ./data:/data
      - /media:/media          # <-- your media tree, same path both sides
```

The identical path matters: subtitle sidecar symlinks in a Jellyfin library
often point at **absolute** targets (e.g. `Movies/Film.mkv ->
/media/Raw/Film/...`). They only resolve inside the container if that exact
path exists there, so mount at `/media:/media`, not `/media:/library`.

**2. Point the scanner at the folders to scan** — set `LIBRARIES` in `.env`.
Each entry is `Name|type|container-path`, separated by `;`. Type is `movies`
or `series`:

```env
LIBRARIES=Movies|movies|/media/Movies;Series|series|/media/Series
```

The legacy movie-only form still works when `LIBRARIES` is empty:

```env
LIBRARY_ROOTS=/media/Movies:/media/Raw
```

If your library uses symlinks with absolute targets, **also include the
target directory** in `SAFE_FS_ROOTS` — the app's safe-fs gate only permits
writes/embeds into declared roots, and embedding a track rewrites the real
(target) file:

```env
SAFE_FS_ROOTS=/media/Raw
```

You can omit the target dir if you only ever write sidecar `.srt` files (those
land next to the symlink, inside `Movies`) and never embed into symlinked
videos.

For translation, add your DeepSeek key:

```env
DEEPSEEK_API_KEY=sk-...
```

### 2. Build and start

```bash
docker compose up -d --build
```

This starts four services: `redis`, `api` (FastAPI), `worker` (ARQ), `web`
(Vite dev server).

### 3. Database migration

The container entrypoint runs `alembic upgrade head` before the API and worker
start. You do not need to run a migration command on TrueNAS Scale or with
Docker Compose. A file lock in `DATA_DIR` makes the API and worker take turns.

For a manual rerun, use `make migrate`. Set `RUN_MIGRATIONS=0` only when an
external process owns the schema.

### 4. Open the UI

```
http://localhost:5173
```

The API is available at `http://localhost:8000`. Interactive API docs are at
`http://localhost:8000/docs`.

---

## Two compose files: development vs. production

There are two compose files, sharing the same `.env` and the same library mount
setup (step 1 above):

| | `docker-compose.yml` | `docker-compose.prod.yml` |
|---|---|---|
| Purpose | Local development | Deploy prebuilt images |
| Images | **Built from source** (`build:`) | **Pulled from Docker Hub** (`jeffrey12cali/subs-manager-{api,web}`) |
| Source code | Bind-mounted (`./api`, `./web`) for **hot reload** | Baked into the image — no source mounts |
| Backend | `uvicorn --reload` | `uvicorn` (production) |
| Frontend | Vite dev server on `5173` | Compiled SPA served by **nginx on `8080`** |
| Web UI | `http://localhost:5173` | `http://localhost:8080` |

The `api` and `web` images are published to Docker Hub automatically by the
GitHub Actions workflow (`.github/workflows/docker-publish.yml`) on every push
to `main`, tagged `latest` and `sha-<commit>`.

**Use the dev file** (`docker compose up -d --build`) while working on the code —
edits reload live. **Use the prod file** to run the app from published images
without a local build:

```bash
docker compose -f docker-compose.prod.yml pull   # fetch latest images
docker compose -f docker-compose.prod.yml up -d
```

Then open `http://localhost:8080`. Pin `:latest` to `:sha-<commit>` in
`docker-compose.prod.yml` for reproducible, rollback-able deploys.

---

## Configuration reference

All settings are read from the `.env` file (or environment variables). The
defaults in `.env.example` are safe for a first run.

The host mount is configured directly in `docker-compose.yml` (see step 1
above), not via an env var. Everything else lives in `.env`:

| Variable | Default | Description |
|---|---|---|
| `LIBRARIES` | *(empty)* | Named libraries: `Name|type|container-path` entries separated by `;`. Type is `movies` or `series`. Preferred over `LIBRARY_ROOTS`. |
| `LIBRARY_ROOTS` | `/library` | Legacy movie-only roots, colon-separated **inside the container**. Used only when `LIBRARIES` is empty. |
| `SAFE_FS_ROOTS` | *(empty)* | Extra colon-separated paths that the write/embed gate allows, such as symlink targets. |
| `RUN_MIGRATIONS` | `1` | Container entrypoint applies Alembic migrations before API/worker start. Set `0` only when an external process owns the schema. |
| `DATA_DIR` | `/data` | Where the DB, trash, and Whisper cache are stored |
| `DATABASE_URL` | `sqlite:////data/subs.db` | SQLite database path |
| `WHISPER_MODEL` | `small` | `tiny` / `base` / `small` / `medium` |
| `WHISPER_COMPUTE_TYPE` | `int8` | `int8` (CPU) or `float16` (GPU) |
| `WHISPER_VAD` | `true` | Voice activity detection filter — reduces hallucinations |
| `DEEPSEEK_API_KEY` | *(empty)* | Required for translation |
| `OPENAI_BASE_URL` | `https://api.deepseek.com/v1` | Any OpenAI-compatible endpoint |
| `TRANSLATE_MODEL` | `deepseek-chat` | Model passed to the translation API |

### Multiple libraries

To scan more than one top-level folder, define each one in `LIBRARIES` and
make sure each root is covered by a mount in `docker-compose.yml`:

```env
LIBRARIES=Movies|movies|/media/Movies;Series|series|/media/Series;TV Shows|series|/media/TV Shows
```

The Library page has a selector for these libraries. "Scan now" scans the
selected library; "Scan all" scans every configured library.

---

## Library folder structure

A movie library expects one folder per title:

```
Movies/
  Stalker (1979)/
    Stalker (1979).mkv
    Stalker (1979).en.srt
    Stalker (1979).ru.forced.srt
  Taxi Driver (1976)/
    Taxi Driver (1976).mkv
    subs/
      Taxi Driver (1976).es.srt
```

Movie folder names must match `Title (Year)` — the year in parentheses is used
for canonical subtitle naming. Sub-folders up to two levels deep are scanned
for subtitle files.

A series library expects one folder per series, with optional season folders:

```
Series/
  Pluribus (2025)/
    Season 01/
      Pluribus S01E01.mkv
      Pluribus S01E01.en.srt
      Pluribus S01E02.mkv
  The Looney Tunes/
    LT_01.mp4
    LT_02.mp4
```

The scanner recognizes `S01E02`, `1x15`, `E04`, and bare numbers such as
`015.mp4` or `LT_15.mp4`. A season number comes from the nearest
`Season 01`, `Temporada 1`, `S01`, or `T01` folder when the filename has no
season. Videos with no reliable episode marker stay visible under
`Other videos` on the series page.

---

## Makefile reference

```
make up           docker compose up -d
make down         docker compose down
make build        rebuild images
make logs         tail all service logs
make migrate      run alembic upgrade head inside api container
make test         run pytest inside api container
make lint         run ruff inside api container
make fmt          run ruff format + fix inside api container
make sh-api       bash shell in api container
make sh-worker    bash shell in worker container
make revision m="msg"  create a new alembic migration
```

---

## Local development (without Docker)

Requires Python 3.11+, `uv`, Node 20+, `ffmpeg`, and `mkvtoolnix` on PATH.

```bash
# Backend
make sync        # uv sync --extra dev
make api-dev     # uvicorn with --reload on :8000

# Worker (separate terminal)
cd api && uv run arq app.workers.queue.WorkerSettings

# Frontend
make web-install  # npm install
make web-dev      # vite dev server on :5173
```

Set environment variables directly or create `api/.env`:

```env
DATABASE_URL=sqlite:///./data/subs.db
DATA_DIR=./data
LIBRARY_ROOTS=/path/to/your/movies
REDIS_URL=redis://localhost:6379/0
DEEPSEEK_API_KEY=sk-...
```

Run migrations locally:

```bash
cd api && uv run alembic upgrade head
```

Run tests:

```bash
make test-local
```

---

## Testing

The API test suite (`api/tests/`) has 389 tests covering the scanner, probe
mapping, naming/canonical paths, safe-fs primitives, job workers (extract,
embed, transcribe, translate), and every API router — including the ARQ
async-enqueue path (mocked `arq.create_pool`) and an end-to-end
scan → upload → translate → embed pipeline test with all externals
(ffprobe, mkvmerge, the translation LLM) mocked.

```bash
cd api && uv run pytest
```

Coverage is reported (not gated) via `pytest-cov`:

```bash
cd api && uv run pytest --cov=app --cov-report=term-missing
```

Current overall coverage: **92%**.

---

## Architecture

```
api/
  app/
    api/          FastAPI routers (libraries, series, movies, subs, video_files, jobs, library, settings)
    core/         Config, DB engine, safe_fs primitives, policy
    models.py     SQLModel table classes
    schemas.py    Pydantic read-models for API responses
    scanner/      Walkers, episode parser, ffprobe wrapper, sub name parser, naming
    workers/      ARQ tasks: scan, extract, embed, transcribe, translate
web/
  src/
    pages/        Library, Series, Movie, Jobs
    components/   LangBadge, UploadModal, EditSubModal
    api/          Typed API client (client.ts)
data/             SQLite DB, trash/, redis/ (created at runtime, gitignored)
```

**Safety contract** — the app never permanently deletes a user file. Subtitle
deletions move files to `data/trash/`. MKV embed operations keep the original
as `<name>.bak.<timestamp>.mkv` for 24 h. Video files cannot be trashed or
overwritten by any code path except the MKV mux flow.

---

## Troubleshooting

### `[Errno 1] Operation not permitted` on `.srt.tmp.*` during translate/write

Symptom: translation fails with `PermissionError: [Errno 1] Operation not permitted`
on a `.srt.tmp.<pid>.<ts>` temp file, even though writing succeeds.

**Cause:** The library is mounted via **SMB/CIFS or NFS without `root_squash`**.
The filesystem refuses `chmod` calls regardless of the caller's permissions.
This is EPERM (errno 1 = "Operation not permitted"), not EACCES (errno 13 =
"Permission denied"). The `open` and `rename` calls succeed; only `chmod` fails.

**Fix:** The app automatically catches EPERM/ENOTSUP on the `chmod` step, logs a
warning, and continues. The file will be written with the umask of the worker
process (typically 0o644), which is correct. No action needed — translation
should succeed. If you still see errors, check that the worker process has
write permission on the library directory.
