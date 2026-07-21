# subs-manager-ai

Self-hosted subtitle manager for a Jellyfin library. Scans movie folders for
external and embedded subtitle tracks, and provides a web UI to upload, rename,
extract from MKV containers, transcribe with Whisper, and translate with
DeepSeek.

---

## Features

- **Library scan** — walks Jellyfin-style `Title (Year)/` folders, parses
  sidecar subtitle filenames (30+ naming patterns), probes MKV embedded tracks
  via ffprobe.
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

**2. Point the scanner at the folders to scan** — set `LIBRARY_ROOTS` in
`.env` to the **container-side** paths (colon-separated):

```env
LIBRARY_ROOTS=/media/Movies
```

If your library uses symlinks with absolute targets, **also include the
target directory** — the app's safe-fs gate only permits writes/embeds into
declared roots, and embedding a track rewrites the real (target) file:

```env
LIBRARY_ROOTS=/media/Movies:/media/Raw
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

### 3. Run the database migration

```bash
make migrate
```

Only needed on first run, or after pulling new commits that include schema
changes.

### 4. Open the UI

```
http://localhost:5173
```

The API is available at `http://localhost:8000`. Interactive API docs are at
`http://localhost:8000/docs`.

---

## Configuration reference

All settings are read from the `.env` file (or environment variables). The
defaults in `.env.example` are safe for a first run.

The host mount is configured directly in `docker-compose.yml` (see step 1
above), not via an env var. Everything else lives in `.env`:

| Variable | Default | Description |
|---|---|---|
| `LIBRARY_ROOTS` | `/library` | Colon-separated paths **inside the container** to scan. Also acts as the write/embed allow-list — include a symlink-target dir here to embed into symlinked videos. |
| `DATA_DIR` | `/data` | Where the DB, trash, and Whisper cache are stored |
| `DATABASE_URL` | `sqlite:////data/subs.db` | SQLite database path |
| `WHISPER_MODEL` | `small` | `tiny` / `base` / `small` / `medium` |
| `WHISPER_COMPUTE_TYPE` | `int8` | `int8` (CPU) or `float16` (GPU) |
| `WHISPER_VAD` | `true` | Voice activity detection filter — reduces hallucinations |
| `DEEPSEEK_API_KEY` | *(empty)* | Required for translation |
| `OPENAI_BASE_URL` | `https://api.deepseek.com/v1` | Any OpenAI-compatible endpoint |
| `TRANSLATE_MODEL` | `deepseek-chat` | Model passed to the translation API |

### Multiple library roots

To scan more than one top-level folder, set `LIBRARY_ROOTS` to a
colon-separated list of **container-side** paths, and make sure each is covered
by a mount in `docker-compose.yml`:

```env
LIBRARY_ROOTS=/media/Movies:/media/Series
```

---

## Library folder structure

The scanner expects one folder per title:

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

Folder names must match `Title (Year)` — the year in parentheses is used for
canonical subtitle naming. Sub-folders up to two levels deep are scanned for
subtitle files.

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

The API test suite (`api/tests/`) has 311 tests covering the scanner, probe
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

Current overall coverage: **91%**.

---

## Architecture

```
api/
  app/
    api/          FastAPI routers (movies, subs, video_files, jobs, library, settings)
    core/         Config, DB engine, safe_fs primitives, policy
    models.py     SQLModel table classes
    schemas.py    Pydantic read-models for API responses
    scanner/      Walker, ffprobe wrapper, sub name parser, canonical naming
    workers/      ARQ tasks: scan, extract, embed, transcribe, translate
web/
  src/
    pages/        Library, Movie, Jobs
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
