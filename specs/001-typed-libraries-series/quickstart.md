# Quickstart: Typed Libraries and Series Browsing

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

## Prerequisites

- The API and worker can see the library roots inside their container or on
  the host.
- The `/jefflix` mount is available read-only or read-write. This feature does
  not write to the library during a scan.
- `uv`, Node 20+, and the existing Docker Compose setup are available.

## 1. Configure named libraries

Add the libraries to `.env`:

```env
LIBRARIES=Movies|movies|/jefflix/Movies;Series|series|/jefflix/Series;TV Shows|series|/jefflix/TV Shows
```

If the series folders use absolute symlinks into `/jefflix/Raw`, declare that
tree as a safe write root for later embed/extract actions:

```env
SAFE_FS_ROOTS=/jefflix/Raw
```

The legacy configuration still works when `LIBRARIES` is empty:

```env
LIBRARY_ROOTS=/jefflix/Movies:/jefflix/Series
```

The legacy form always creates `movies` libraries. Use `LIBRARIES` when a root
holds series.

## 2. Apply the database migration

Docker and TrueNAS: automatic. The image entrypoint runs
`alembic upgrade head` before the API and worker start. A file lock in
`DATA_DIR` makes the two containers take turns. First start may take longer
while the migration runs.

Manual rerun:

```bash
make migrate
```

Local:

```bash
cd api
uv run alembic upgrade head
```

Expected: the `series` table exists and `movie` has the new library and
episode columns. Existing rows keep their IDs and subtitle links.

## 3. Start the application

Docker:

```bash
docker compose up -d --build
```

Local:

```bash
make api-dev
make web-dev
```

Open `http://localhost:5173`.

## 4. Validate the library selector

1. Open the Library page.
2. Confirm the selector shows `Movies`, `Series`, and `TV Shows`.
3. Select `Movies`. Confirm only movie cards appear.
4. Select `Series`. Confirm only series cards appear.
5. Reload the page. Confirm the same library remains selected.

Expected: the selected library appears in the page address. The Library page
shows zero items from a different library.

## 5. Validate series discovery on `/jefflix`

Use the API or the UI after a scan.

Expected series and episode examples:

| Fixture | Expected result |
|---------|-----------------|
| `Series/Pluribus (2025)` | One series. Season 1 contains `S01E01` and `S01E02`. |
| `Series/The Looney Tunes` | One yearless series. `LT_01.mp4` through `LT_50.mp4` appear as unseasoned episodes `E01` through `E50`. |
| `Series/El Siguiente Programa (1997)` | Four season groups from `Temporada 1` to `Temporada 4`. Episodes ordered by `1xNN`, `2xNN`, and so on. |
| `TV Shows/Cowboy Bebop (1998)` | One series with `E01` through `E26` in the unseasoned episode group. |
| `TV Shows/Crayon Shin-chan (1992)` | Season groups from `Season 01` onward. `S06E214` appears in season 6. |
| `TV Shows/Doraemon (1979)` | Season 1 follows the symlinked season folder. The ` - LAT` files group with their matching episode as variants. |
| `TV Shows/One Piece (1999)` | Season folders and bare-number files appear without crashes. Unmatched release names appear in `Other videos`. |

A file must appear exactly once: in a numbered episode or in `Other videos`.

## 6. Validate the episode detail view

1. Open the `Pluribus` series.
2. Select `S01E01`.
3. Confirm the page shows the same sections as a movie detail page: video
   files, embedded tracks, external subtitles, upload, edit, delete, detect,
   extract, embed, transcribe, and translate.
4. Upload a small SRT with language `en`.
5. Confirm the file lands next to the episode video as
   `Pluribus S01E01.en.srt`.
6. Confirm `S01E02` does not show the new subtitle.

Do not run step 4 against `/jefflix` during validation unless you intend to
write a subtitle. Use a temporary copy or a test library for write checks.

## 7. Run the automated checks

```bash
cd api && uv run pytest
cd web && npm run build
```

Focused checks:

```bash
cd api && uv run pytest -q tests/test_config.py tests/test_episode_parser.py \
  tests/test_walker.py tests/test_scanner.py tests/test_series_api.py \
  tests/test_libraries_api.py tests/test_movies_api.py tests/test_subs_api.py
```

Expected: all tests pass and the TypeScript build succeeds.

## 8. Read-only dry run on `/jefflix`

Use a temporary database and data directory. Do not point the app at the real
`./data` directory.

Parser-only pass:

```bash
cd api
uv run python - <<'PY'
from pathlib import Path
from app.scanner.walker import walk_series_library

for root in (Path('/jefflix/Series'), Path('/jefflix/TV Shows')):
    for series in walk_series_library(root):
        print(series.title, series.year, len(series.videos))
PY
```

Scanner pass for selected fixture folders. Build a temporary root with
symlinks so the scan covers a small set and never writes inside `/jefflix`:

```bash
cd api
TMP=$(mktemp -d)
mkdir -p "$TMP/series"
ln -s "/jefflix/Series/Pluribus (2025)" "$TMP/series/"
ln -s "/jefflix/Series/The Looney Tunes" "$TMP/series/"
ln -s "/jefflix/TV Shows/Cowboy Bebop (1998)" "$TMP/series/"
export TMP_ROOT="$TMP/series"
DATABASE_URL="sqlite:///$TMP/dry.db" DATA_DIR="$TMP/data" \
uv run python - <<'PY'
from pathlib import Path
from sqlmodel import Session, SQLModel, create_engine
from app.scanner.scanner import scan_library
import os

root = Path(os.environ['TMP_ROOT'])
engine = create_engine(os.environ['DATABASE_URL'])
SQLModel.metadata.create_all(engine)
with Session(engine) as session:
    stats = scan_library(
        root,
        session,
        probe_runner=lambda _path: {"format": {}, "streams": []},
        kind='series',
        library_id='series',
    )
    print(stats)
PY
rm -rf "$TMP"
```

Set `TMP_ROOT="$TMP/series"` in the command environment before the Python
block. Expected statistics: `series: 3`, `episodes: 78`, `videos: 78`, and no
exception. Pluribus has 2 episodes, The Looney Tunes has 50, and Cowboy Bebop
has 26.

The library tree has the same file count before and after:

```bash
find /jefflix -type f | wc -l
find /jefflix -type l | wc -l
```

The scan may read media for hashing. It must not create, change, or delete a
library file.

## 9. Troubleshooting

| Symptom | Check |
|---------|-------|
| A configured library is missing | Confirm the entry has exactly three `|`-separated fields, the type is `movies` or `series`, and the ID is unique. Check the API log. |
| A symlinked season has no episodes | Confirm the series walker follows directory symlinks and the depth is at most two levels below the series folder. |
| An episode appears in `Other videos` | Confirm the filename has `SxxExx`, `NxNN`, `E##`, or a supported bare number. Check the parser log for a rejected year or resolution. |
| A subtitle appears on the wrong episode | Do not assign it manually. Check the matching rule and the debug log. A rescan must not attach an ambiguous subtitle. |
| A subtitle lands in the series folder | Confirm `subtitle_dir` and `subtitle_stem` are set for the episode. Rows from before the migration need a rescan. |
| Embed or extract fails with a path error | Add the symlink target tree to `SAFE_FS_ROOTS`. |
