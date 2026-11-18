# Implementation Plan: Typed Libraries and Series Browsing

**Branch**: `feat-env-library-series-episode-view` | **Date**: 2026-11-17 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-typed-libraries-series/spec.md`

## Summary

Add named, typed libraries to `.env` and make the Library page library-aware.
Add a series-library scan path that groups videos into episodes and exposes a
series page. Reuse the existing `Movie` row as the media item for both movies
and episodes, so every existing subtitle action (upload, edit, delete, detect,
rename, extract, embed, transcribe, translate) works for an episode without a
second action pipeline. Episode pages use the existing movie detail page
component under a new `/episodes/:id` route.

The scanner stays read-only for media. Subtitle output names move from
`movie.folder_path` plus title/year to persisted `subtitle_dir` plus
`subtitle_stem`, which gives each episode its own collision-free sidecar
namespace.

## Technical Context

**Language/Version**: Python 3.11 (API/worker), TypeScript 5.6 + React 18 (web)

**Primary Dependencies**: FastAPI, SQLModel, Alembic, ARQ, Pydantic Settings,
pytest; React Router, TanStack Query, Vite, Tailwind CSS

**Storage**: SQLite via SQLModel; media stays on the mounted filesystem

**Testing**: `cd api && uv run pytest`; `cd web && npm run build`; optional
read-only dry run over `/jefflix` with a temporary database and data directory

**Target Platform**: Linux server in Docker Compose, browser UI on LAN

**Project Type**: Web application (FastAPI backend + React frontend)

**Performance Goals**: A library-page query returns in under 1 second for a
library with 2,000 episodes. A series page returns in under 1 second for a
series with 1,000 episodes. A scan remains linear in file count.

**Constraints**: No new runtime dependency. Scan writes zero bytes inside a
library root. Existing movie routes and subtitle behavior stay compatible.
SQLite schema changes use Alembic. Do not break the legacy `LIBRARY_ROOTS`
configuration.

**Scale/Scope**: Up to 10 named libraries, 100,000 episodes, 1,000 series per
library. The supplied `/jefflix` tree is the reference dataset.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Status | Evidence |
|------|--------|----------|
| I. Media Safety | PASS | Scanner only reads media. Subtitle writes go through `atomic_write`/`trash`; no new deletion path. Episode output uses the same safe-fs helpers. |
| II. Library Fidelity | PASS | Series walker emits every video exactly once. Numbered episodes group by series/season/episode. Unnumbered videos get their own item. Unmatched subtitles stay unassigned. |
| III. Test-Backed Changes | PASS | Plan includes parser, walker, scanner, API, config, migration, and frontend build checks. Existing tests remain in the suite. |
| IV. Small, Config-Driven Changes | PASS | One config variable adds named libraries. `Movie` is reused instead of adding a second media/action pipeline. No new dependency. |

**Post-design re-check**: PASS. The `Movie` reuse and synthetic episode
`folder_path` are the only design choices that need explanation; both are in
Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/001-typed-libraries-series/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── libraries-api.md
│   ├── movies-api.md
│   └── series-api.md
├── checklists/
│   └── requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
api/
├── alembic/versions/
│   └── 20261117_0002_typed_libraries_series.py
├── app/
│   ├── api/
│   │   ├── libraries.py          # new: configured library list
│   │   ├── series.py             # new: series list/detail
│   │   ├── library.py            # scan by library, legacy roots kept
│   │   ├── movies.py             # library filter; episode detail fields
│   │   └── subs.py               # canonical path via item fields
│   ├── core/
│   │   ├── config.py             # LIBRARIES parsing + legacy fallback
│   │   └── safe_fs.py            # allow all configured library roots
│   ├── scanner/
│   │   ├── episode_parser.py     # new: season/episode marker parser
│   │   ├── walker.py             # movie walker unchanged; series walker
│   │   ├── scanner.py            # scan_movie_library / scan_series_library
│   │   └── naming.py             # stem-based canonical names
│   ├── workers/
│   │   ├── mkv.py
│   │   ├── transcribe.py
│   │   ├── translate.py
│   │   └── translate_embedded.py # use item subtitle_dir/subtitle_stem
│   ├── models.py                 # Series; Movie episode/library fields
│   └── schemas.py                # library, series, episode read models
└── tests/
    ├── test_config.py
    ├── test_episode_parser.py
    ├── test_walker.py
    ├── test_scanner.py
    ├── test_series_api.py
    ├── test_libraries_api.py
    ├── test_movies_api.py
    └── test_subs_api.py

web/src/
├── api/client.ts                 # library/series calls + types
├── App.tsx                       # /series/:id, /episodes/:id
├── pages/
│   ├── Library.tsx               # selector, movie grid or series grid
│   ├── Series.tsx                # new: seasons + episodes + Other videos
│   └── Movie.tsx                 # reused for episodes; series breadcrumb
└── components/                   # existing components reused
```

**Structure Decision**: Keep the existing single web app with `api/` and
`web/`. Add two backend routers and one frontend page. Do not create a second
media or action pipeline.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Reuse `Movie` rows for episodes | All existing subtitle actions, jobs, workers, and the detail page already key on `movie_id`. | A separate `Episode` table would duplicate nine action paths, worker logic, and frontend code. |
| Synthetic `folder_path` for episodes | The existing unique constraint and many code paths treat `folder_path` as the item identity. A stable synthetic key avoids a destructive SQLite table rebuild and keeps idempotent scans. | Dropping the unique constraint requires a full SQLite table rebuild and touches every scan path. |
| Persisted `subtitle_dir`/`subtitle_stem` | Episodes need sidecars next to the episode video with a video-derived filename, not next to the series folder with a title/year name. | Deriving from `Movie.title`/`year` would produce collisions and names that media servers do not associate with the episode. |

## Phase 0: Research

See [research.md](./research.md). Decisions cover config syntax, library
identity, episode identity, parser precedence, symlink traversal, subtitle
association, and canonical naming.

## Phase 1: Design

- [data-model.md](./data-model.md)
- [contracts/libraries-api.md](./contracts/libraries-api.md)
- [contracts/movies-api.md](./contracts/movies-api.md)
- [contracts/series-api.md](./contracts/series-api.md)
- [quickstart.md](./quickstart.md)
