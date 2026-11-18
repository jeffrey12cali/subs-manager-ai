# Research: Typed Libraries and Series Browsing

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

## R1. Named library configuration syntax

**Decision**: Add one environment variable, `LIBRARIES`. Each entry is
`name|type|root`, and entries are separated by `;`.

```env
LIBRARIES=Movies|movies|/jefflix/Movies;Series|series|/jefflix/Series;TV Shows|series|/jefflix/TV Shows
```

Trim whitespace around entries and fields. A name may contain spaces but not
`|` or `;`. A root may contain spaces but not `;`. Valid types are `movies`
and `series`. An invalid or duplicate entry is skipped and logged. When
`LIBRARIES` is empty, the existing colon-separated `LIBRARY_ROOTS` becomes one
movie library per root.

**Rationale**: The format is readable in `.env`, needs no JSON quoting, and
handles the spaces in `TV Shows`. It keeps one variable that the operator can
edit without a code change.

**Alternatives considered**:

- JSON array: correct but hard to read and easy to break with quoting.
- One variable per library (`LIBRARY_MOVIES=...`): no type field and becomes
  verbose with many libraries.
- Auto-detect type: the same root can hold both kinds, and detection would be
  unreliable. The spec requires an explicit type.

## R2. Library identity

**Decision**: Derive a stable `library_id` by lowercasing the display name,
replacing each run of non-alphanumeric characters with `-`, and trimming
leading/trailing `-`. Reject a later entry when the resulting ID is already
used. Store the ID on `Movie` and `Series` rows.

**Rationale**: The ID is readable in URLs and API calls, and it stays stable
across restarts while the `.env` entry is unchanged. A display name can still
have spaces and mixed case.

**Alternatives considered**:

- Use the root path as the ID: long, contains slashes, awkward in URLs.
- Use a database-generated ID: configuration lives in `.env`, so the app would
  have to sync rows at startup. That adds a write path and conflict rules.

## R3. Reuse the movie row for episodes

**Decision**: Extend the `Movie` table with `kind` (`movie` or `episode`),
`library_id`, `series_id`, `season_number`, `episode_number`,
`episode_label`, `subtitle_dir`, and `subtitle_stem`. Keep `movie_id` foreign
keys on video files, subtitle files, and jobs. Add a separate `Series` table.

**Rationale**: Every subtitle action already resolves a `Movie` row and then a
video or subtitle row. Reusing that row keeps upload, edit, delete, detect,
rename, extract, embed, transcribe, and translate on one code path. The
episode detail page can reuse the movie detail page.

**Alternatives considered**:

- Separate `Episode` table: cleaner names, but duplicates nine action paths,
  the worker jobs, the API schemas, and the detail page.
- Rename `Movie` to `MediaItem`: a large migration and code churn without new
  user value.

## R4. Episode identity and synthetic folder path

**Decision**: For a numbered episode, set `folder_path` to
`<series folder>#<relative parent>S<season>E<episode>` when the season is
known, or `<series folder>#<relative parent>E<episode>` when it is not. For an
unnumbered video, use `<series folder>#<relative video path>`. The UI does not
show this value as a real folder. Persist the real output directory in
`subtitle_dir` and the real file stem in `subtitle_stem`.

**Rationale**: `movie.folder_path` has a unique constraint and is the current
item identity. A synthetic path keeps idempotent scans and avoids a destructive
SQLite table rebuild. `subtitle_dir` and `subtitle_stem` give subtitle output
the correct real location.

**Alternatives considered**:

- Drop the unique constraint: SQLite needs a table rebuild for an unnamed
  unique constraint, and many code paths assume `folder_path` identifies one
  item.
- Use the primary video path as `folder_path`: the primary can change when a
  variant is added or removed, which would create duplicate rows.
- Add a separate `item_key`: a second identity column adds a migration and a
  fallback path for every lookup without a user-visible benefit.

## R5. Episode marker parser precedence

**Decision**: Parse in this order and stop at the first strong match:

1. `S<season>E<episode>` with optional separators, for example `S01E02`,
   `S01.E02`, `s1e2`.
2. `<season>x<episode>`, for example `1x15`. Reject a match that is part of a
   resolution such as `1920x1080`.
3. `E<episode>` with a boundary, for example `E04`.
4. A leading bare number (`015 - Title.mp4`, `069.mp4`) or a trailing
   underscore number (`LT_15.mp4`). Reject numbers that look like a year
   (`1900`-`2099` without a leading zero) or a resolution (`480`, `720`,
   `1080`, `2160` when followed by `p` or `i`).

Use the nearest parent folder that matches `Season <n>`, `Temporada <n>`,
`S<n>`, or `T<n>` as the season when the filename has no season. An explicit
filename season wins over a folder season.

**Rationale**: The reference tree contains all of these forms. Precedence
avoids treating a year or resolution as an episode. The folder fallback
handles `Season 06/Crayon Shin-chan S06E214.mp4` and files named only `01.mp4`.

**Alternatives considered**:

- One combined regex: hard to explain, hard to test, and easy to mis-rank.
- External media metadata: the app has no metadata provider and the spec does
  not add one.

## R6. Symlinked series and season folders

**Decision**: Walk a series library with directory symlinks followed, a depth
limit of two inner levels, and a visited-real-directory set. Keep the lexical
path for display and the real path for probing and writes. Do not follow
symlinks for movie libraries beyond the current behavior.

**Rationale**: `/jefflix/Series/Over the Garden Wall (2014)` and
`/jefflix/Series/Yo Soy Betty la Fea (1999)/Season 01` are symlinked
directories. `os.walk(followlinks=False)` would hide their episodes. A visited
set prevents loops.

**Alternatives considered**:

- Follow all symlinks in the movie walker too: changes existing movie behavior
  and increases the risk of loops in unrelated trees.
- Use `Path.rglob`: follows symlinks unpredictably and has no depth or loop
  control.

## R7. Subtitle association and canonical names

**Decision**: Attach a subtitle to an episode when one of these tests passes,
in order: the subtitle stem starts with a video stem plus a delimiter; the
subtitle's episode marker matches exactly one episode group; the subtitle is
in a directory with exactly one episode group. Otherwise leave it unassigned
and count it in scan statistics.

Generate sidecar names as
`<subtitle_stem>.<language>[.forced][.sdh][.<tag>].<ext>`, where
`subtitle_stem` is the primary episode video stem with a recognized variant
suffix (` - ESP`, ` - LAT`, ` - EN`, and similar) removed. Use the same helper
from the upload, rename, extract, transcribe, translate, and embed flows.

**Rationale**: Episode sidecars must name the episode video, not the series.
Reusing one helper avoids drift between nine call sites. The "exactly one
group" rule prevents a generic `subs/3_English.srt` from landing on the wrong
episode.

**Alternatives considered**:

- Attach every unmatched subtitle to the first episode: can corrupt the wrong
  episode.
- Keep title/year naming for episodes: produces collisions and names that a
  media server does not pair with the episode.
- Store subtitles in a series-level pool: the episode detail page would need a
  second association UI and actions would become ambiguous.

## R8. API and URL shape

**Decision**:

- `GET /libraries` lists configured libraries.
- `GET /movies/?library=<id>` returns movies for a movie library.
- `GET /series/?library=<id>` lists series summaries.
- `GET /series/{id}` returns seasons and episodes.
- `GET /movies/{id}` stays the episode detail payload.
- `POST /library/scan?library=<id>` scans one library; no parameter scans all.
- Web routes: `/?library=<id>`, `/series/:id`, `/episodes/:id`; the episode
  route renders the existing movie detail component.

**Rationale**: It keeps existing movie endpoints and the existing detail
component. A query parameter is enough to make the selected library
bookmarkable.

**Alternatives considered**:

- A nested path such as `/libraries/{id}/movies`: more REST-like but adds a
  second movie route that duplicates the existing one.
- A global client-side store with no URL state: a refresh loses the selection.

## R9. Database migration

**Decision**: Add Alembic revision `0002_typed_libraries_series`. Create the
`series` table. Add nullable columns to `movie`, backfill them for existing
rows (`kind='movie'`, `library_id=NULL`, `subtitle_dir=folder_path`,
`subtitle_stem=Title (Year)` or `Title`), then make `kind` non-null with a
server default of `movie`. Keep the `folder_path` unique constraint.

**Rationale**: Nullable additions and an in-place backfill work on SQLite
without a table rebuild. Existing rows stay visible and a rescan fills
`library_id`.

**Alternatives considered**:

- A new table with a data copy: more risk, and it drops the stable IDs that
  jobs and subtitles reference.
- `alembic autogenerate` alone: the backfill and the episode identity need
  explicit SQL.

## R10. Read-only validation against `/jefflix`

**Decision**: Validate parsing with a pure walker/parser pass. Validate the
scanner on selected fixture folders with a temporary `DATABASE_URL` and
`DATA_DIR` and a no-op probe runner. Do not start the app with the real data
directory. Never run upload, delete, extract, embed, transcribe, or translate
against `/jefflix`.

**Rationale**: The scanner already prevents media writes, but validation must
not depend on that alone. A pure pass also avoids probing 1,300 symlinked
videos.

**Alternatives considered**:

- Full scan of all of `/jefflix`: slow and unnecessary for parser validation.
- Docker Compose against the real mount: could create job rows and data files
  in the real data directory.
