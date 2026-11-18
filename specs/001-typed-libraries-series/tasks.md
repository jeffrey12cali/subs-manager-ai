---
description: "Task list for Typed Libraries and Series Browsing"
---

# Tasks: Typed Libraries and Series Browsing

**Input**: Design documents from `/specs/001-typed-libraries-series/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/,
quickstart.md

**Tests**: Included. The project has an existing pytest suite, and the
constitution requires test-backed changes.

**Organization**: Tasks are grouped by user story. Each story is independently
testable after the foundational phase.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: User story label (`US1` to `US4`)
- Every task includes an exact file path
- Entity fields cite `data-model.md` as `Entity.field`

## Phase 1: Setup

**Purpose**: Document the configuration surface and prepare the feature
artifacts.

- [x] T001 Add the `LIBRARIES` syntax, the `SAFE_FS_ROOTS` symlink note, and the
  episode sidecar examples to `.env.example`.
- [x] T002 [P] Add a short "libraries and series" section to `README.md` that
  points to `specs/001-typed-libraries-series/quickstart.md`.
- [x] T003 [P] Create the initial `api/tests/test_episode_parser.py` test file
  with the reference filename table from `research.md` R5.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared configuration, schema, migration, naming, and scan
plumbing that every user story needs.

**CRITICAL**: No user story work can begin until this phase is complete.

- [x] T004 Implement `LIBRARIES` parsing, validation, ID derivation, and the
  legacy `LIBRARY_ROOTS` fallback in `api/app/core/config.py`; add tests to
  `api/tests/test_config.py`. Covers `Library.name`, `Library.type`,
  `Library.root`, and `Library.id` (`data-model.md`).
- [x] T005 [P] Add `MediaKind`, the `Series` table, and the new `Movie` fields
  in `api/app/models.py`. Covers `Series.library_id`, `Series.folder_path`,
  `Series.title`, `Series.year`, `Movie.kind`, `Movie.library_id`,
  `Movie.series_id`, `Movie.season_number`, `Movie.episode_number`,
  `Movie.episode_label`, `Movie.subtitle_dir`, and `Movie.subtitle_stem`
  (`data-model.md`).
- [x] T006 Create the Alembic revision
  `api/alembic/versions/20261117_0002_typed_libraries_series.py` with the
  `series` table, new `movie` columns, indexes, and the backfill described in
  `data-model.md` "Migration".
- [x] T007 [P] Add `LibraryRead`, extend `MovieSummary` and `MovieDetail`, and
  add `EpisodeSummary`, `SeriesSummary`, and `SeriesDetail` to
  `api/app/schemas.py`. Covers `MovieDetail.kind`, `MovieDetail.series_title`,
  `MovieDetail.episode_label`, and the read models in `data-model.md`.
- [x] T008 [P] Add `canonical_sub_filename_for_stem`,
  `canonical_sub_path_for_stem`, and `is_canonical_for_stem` to
  `api/app/scanner/naming.py`; keep the existing title/year helpers; add tests
  to `api/tests/test_naming.py`. Covers `Movie.subtitle_dir` and
  `Movie.subtitle_stem` (`data-model.md`).
- [x] T009 [P] Add all configured library roots to the safe-fs allow-list in
  `api/app/core/safe_fs.py` and extend `api/tests/test_safe_fs.py`.
- [x] T010 Change `scan_library` in `api/app/scanner/scanner.py` to accept
  `kind` and `library_id`, and pass both from `api/app/workers/queue.py` and
  the synchronous fallback in `api/app/api/library.py`. Keep the existing
  movie behavior when `kind` is omitted. Covers `Movie.library_id`
  (`data-model.md`).
- [x] T011 Update every sidecar writer (`api/app/api/subs.py`,
  `api/app/workers/mkv.py`, `api/app/workers/transcribe.py`,
  `api/app/workers/translate.py`, `api/app/workers/translate_embedded.py`) to
  use `Movie.subtitle_dir`, `Movie.subtitle_stem`, and the stem-based naming
  helpers with a fallback for old rows. Covers `Movie.subtitle_dir` and
  `Movie.subtitle_stem` (`data-model.md`).
- [x] T012 Add the new `api/app/api/libraries.py` router with
  `GET /libraries`, register it in `api/app/main.py`, and add
  `api/tests/test_libraries_api.py` for the contract in
  `contracts/libraries-api.md`.

**Checkpoint**: Configuration, schema, migration, naming, safe-fs, scan
plumbing, and the library list endpoint are ready.

---

## Phase 3: User Story 1 - Define and switch named libraries (Priority: P1) 🎯 MVP

**Goal**: The user sees every configured library, selects one, and sees only
that library's items.

**Independent Test**: Define one movie and one series library, open the UI,
switch between them, and reload. Each view shows only the active library.

### Tests for User Story 1

- [x] T013 [P] [US1] Add library filtering tests to
  `api/tests/test_movies_api.py`: valid `movies` library, unknown library
  (`404`), and a `series` library (`422`).
- [x] T014 [P] [US1] Add frontend type and build coverage for the library
  selector through the TypeScript build in `web/package.json`.

### Implementation for User Story 1

- [x] T015 [US1] Add the `library` query filter to `list_movies` in
  `api/app/api/movies.py`, including the `library_id = NULL` root-prefix
  fallback from `data-model.md` "Library Filtering".
- [x] T016 [US1] Add `getLibraries` and the `Library` type to
  `web/src/api/client.ts`.
- [x] T017 [US1] Update `web/src/pages/Library.tsx` to load libraries, show a
  selector, keep the active library in the `library` query parameter, default
  to the first library, and render the movie grid only for a `movies` library.
- [x] T018 [US1] Pass the active library ID to the scan call and add a
  regression test for the empty-library and invalid-library states in
  `web/src/pages/Library.tsx` through the TypeScript build.

**Checkpoint**: US1 works with the existing movie scanner and the new library
selector.

---

## Phase 4: User Story 2 - Browse a series and open an episode (Priority: P1)

**Goal**: A series library shows series cards, a series page lists seasons and
episodes, and an episode opens the same detail and action view as a movie.

**Independent Test**: Scan a series fixture with `SxxExx` files in season
folders, open the series, select an episode, and exercise one subtitle action.

### Tests for User Story 2

- [x] T019 [P] [US2] Add episode parser tests to
  `api/tests/test_episode_parser.py` for `S01E02`, `1x15`, `E04`, bare
  `015.mp4`, `LT_15.mp4`, `Season 06` fallback, year rejection, and resolution
  rejection.
- [x] T020 [P] [US2] Add series walker tests to `api/tests/test_walker.py` for
  a yearless series, a season folder, a symlinked season folder, and variant
  grouping.
- [x] T021 [P] [US2] Add series scan tests to `api/tests/test_scanner.py` for
  series and episode rows, variant grouping, idempotency, subtitle
  association, and unmatched subtitle statistics. Covers `Series.title`,
  `Movie.series_id`, `Movie.season_number`, and `Movie.episode_number`
  (`data-model.md`).
- [x] T022 [P] [US2] Add contract tests to `api/tests/test_series_api.py` for
  the list, detail, season ordering, and `Other videos` response.
- [x] T023 [P] [US2] Add episode detail tests to
  `api/tests/test_movies_api.py` for `kind`, `series_title`, and
  `episode_label`.
- [x] T024 [P] [US2] Add an episode upload test to
  `api/tests/test_subs_api.py` that asserts the sidecar path uses the episode
  directory and video stem.

### Implementation for User Story 2

- [x] T025 [US2] Implement `api/app/scanner/episode_parser.py` with the
  precedence rules from `research.md` R5 and return a season, episode number,
  and label.
- [x] T026 [US2] Add `walk_series_library` and the series walk dataclasses to
  `api/app/scanner/walker.py`, including symlink-following with a depth limit
  and a visited-real-directory set. Covers `Series.folder_path` and
  `Movie.season_number` (`data-model.md`).
- [x] T027 [US2] Implement `scan_series_library` in
  `api/app/scanner/scanner.py`: upsert `Series`, group videos by
  series/season/episode, compute the synthetic `folder_path`, set
  `subtitle_dir` and `subtitle_stem`, and reuse `_upsert_video_file`. Covers
  `Movie.folder_path`, `Movie.subtitle_dir`, and `Movie.subtitle_stem`
  (`data-model.md`).
- [x] T028 [US2] Implement subtitle association in
  `api/app/scanner/scanner.py` using the matching order from `research.md` R7
  and count unassigned subtitles in the scan stats. Covers
  `ExternalSubtitle.movie_id` (`data-model.md`).
- [x] T029 [US2] Add `api/app/api/series.py` with `GET /series/` and
  `GET /series/{id}`, register it in `api/app/main.py`, and implement the
  season grouping and ordering from `contracts/series-api.md`.
- [x] T030 [US2] Extend `GET /movies/{id}` in `api/app/api/movies.py` with the
  `kind`, `series_id`, `series_title`, season, episode, and label fields.
- [x] T031 [US2] Add `getSeries`, `getSeriesDetail`, `SeriesSummary`,
  `SeriesDetail`, and `EpisodeSummary` to `web/src/api/client.ts`.
- [x] T032 [US2] Create `web/src/pages/Series.tsx` to show season groups,
  ordered episodes, and links to the episode detail route.
- [x] T033 [US2] Add `/series/:id` and `/episodes/:id` routes to
  `web/src/App.tsx`; render the existing `Movie` page for the episode route.
- [x] T034 [US2] Update `web/src/pages/Movie.tsx` to show the series
  breadcrumb, `series_title`, and `episode_label` for an episode, and hide the
  synthetic `folder_path`.
- [x] T035 [US2] Update `web/src/pages/Library.tsx` to render series cards and
  link them to `/series/:id` when the active library is a `series` library.

**Checkpoint**: US2 works end to end for numbered episodes, including subtitle
actions.

---

## Phase 5: User Story 3 - Keep unnumbered videos reachable (Priority: P2)

**Goal**: Videos without a reliable episode number stay visible in a flat
`Other videos` list and open the same episode detail view.

**Independent Test**: Add two unnumbered videos and one numbered episode to a
series. Confirm the numbered episode is in its season group and both
unnumbered files are in `Other videos` and open a detail page.

### Tests for User Story 3

- [x] T036 [P] [US3] Add scanner tests for yearless series folders and
  unnumbered videos that assert one media item per unnumbered video. Covers
  `Movie.episode_number = null` and `Movie.episode_label` (`data-model.md`).
- [x] T037 [P] [US3] Add series API tests for the `other_videos` list and a
  numbered episode with an unknown season.

### Implementation for User Story 3

- [x] T038 [US3] Extend `scan_series_library` in
  `api/app/scanner/scanner.py` to create one stable item per unnumbered video
  with the synthetic path rule from `research.md` R4.
- [x] T039 [US3] Render `other_videos` as a flat `Other videos` section in
  `web/src/pages/Series.tsx` with links to the episode detail route.
- [x] T040 [US3] Show the video filename as the episode label for an
  unnumbered item in `web/src/pages/Movie.tsx`.

**Checkpoint**: Every video under a series library appears exactly once.

---

## Phase 6: User Story 4 - Scan one library or all libraries (Priority: P2)

**Goal**: The user can scan the active library or every configured library.

**Independent Test**: Scan one of two libraries, confirm only its jobs run,
then scan all and confirm jobs for both.

### Tests for User Story 4

- [x] T041 [P] [US4] Add scan tests to `api/tests/test_library_api.py` for
  `library=<id>`, unknown library (`404`), and all-library scan. Assert that a
  failure in one root does not block the other.
- [x] T042 [P] [US4] Add a worker test in `api/tests/test_enqueue_async.py`
  that checks the scan job params carry `kind` and `library_id`.

### Implementation for User Story 4

- [x] T043 [US4] Add the `library` query parameter to `trigger_scan` in
  `api/app/api/library.py`, resolve one or all configured libraries, and keep
  the legacy DB-root and `LIBRARY_ROOTS` fallback.
- [x] T044 [US4] Update `run_scan` in `api/app/workers/queue.py` to pass
  `kind` and `library_id` to `scan_library` and log series/episode stats.
- [x] T045 [US4] Add a "Scan all" action next to "Scan now" in
  `web/src/pages/Library.tsx`; "Scan now" uses the active library, "Scan all"
  sends no library parameter.

**Checkpoint**: Both scan scopes work and report jobs.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, real-library validation, and final quality gates.

- [x] T046 [P] Update `README.md` and `.env.example` with the final
  `LIBRARIES` format, legacy fallback, symlink/safe-root note, and the series
  UI behavior.
- [x] T047 Run `cd api && uv run alembic upgrade head` against a temporary
  SQLite database, then `uv run alembic downgrade base` and
  `uv run alembic upgrade head` again; fix any migration issue in
  `api/alembic/versions/20261117_0002_typed_libraries_series.py`.
- [x] T048 Run the read-only `/jefflix` parser dry run and a selected-fixture
  scan with a temporary `DATABASE_URL` and `DATA_DIR`; confirm the expected
  fixtures from `quickstart.md` and confirm the library file/link counts do
  not change.
- [x] T049 Run `cd api && uv run pytest` and fix all failures; keep the full
  suite green.
- [x] T050 Run `cd web && npm run build` and fix all TypeScript or build
  failures.
- [x] T051 Run `cd api && uv run ruff check app` and fix lint errors in touched
  files.
- [x] T052 Review the final diff against `spec.md` and `contracts/`; remove
  any task that added behavior outside the feature scope.

---

## Dependencies & Execution Order

### Phase Dependencies

- Phase 1 has no dependency.
- Phase 2 depends on Phase 1. It blocks every user story.
- Phase 3 (US1) depends on Phase 2. It is the MVP.
- Phase 4 (US2) depends on Phase 2 and can start after US1's config and model
  work. It does not require US1's UI tasks.
- Phase 5 (US3) depends on US2's scanner and series page.
- Phase 6 (US4) depends on Phase 2's scan plumbing and can run in parallel
  with US2.
- Phase 7 depends on all user stories.

### User Story Dependencies

- **US1**: independent after Phase 2.
- **US2**: independent after Phase 2.
- **US3**: depends on US2 for series grouping and the series page.
- **US4**: independent after Phase 2.

### Parallel Opportunities

- T005, T007, T008, T009 can run in parallel in Phase 2.
- T013 and T014 can run in parallel.
- T019 through T024 are independent test files.
- T025 and T026 can run in parallel; T027 depends on T025 and T026.
- T029 and T030 are separate routers.
- T031 through T035 are separate frontend files.
- T041 and T042 are separate test files.
- T046, T047, T048 can run in parallel after implementation.

## Parallel Example: User Story 2

```bash
# Parser and walker work can proceed together:
Task T025: api/app/scanner/episode_parser.py
Task T026: api/app/scanner/walker.py

# API and frontend work can proceed after T027:
Task T029: api/app/api/series.py
Task T030: api/app/api/movies.py
Task T031: web/src/api/client.ts
Task T032: web/src/pages/Series.tsx
```

## Implementation Strategy

### MVP First

1. Complete Phase 1 and Phase 2.
2. Complete Phase 3 (US1) and validate the library selector.
3. Stop and demo the named library selector with the existing movie library.

### Incremental Delivery

1. US1: named libraries and selector.
2. US2: series scan, series page, episode detail, subtitle actions.
3. US3: unnumbered videos remain visible.
4. US4: scan one or all libraries.
5. Polish: docs, migration round trip, `/jefflix` dry run, full test suite,
   frontend build, lint.

### Notes

- Use a temporary database and data directory for every `/jefflix` check.
- Never run a write action against `/jefflix` during validation.
- Keep all new routes backward compatible with the existing movie routes.
- Do not add a dependency; the current stack covers the feature.
