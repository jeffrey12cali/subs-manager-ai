# Feature Specification: Typed Libraries and Series Browsing

**Feature Branch**: `feat-env-library-series-episode-view`

**Created**: 2026-11-17

**Status**: Draft

**Input**: User description: "Implement the use of the application over other libraries that can be specified through the .env file. Also support series with a view where the episodes are listed, and if the user clicks any episode they get the same view as when they click a movie."

## Context

Today the application scans one or more filesystem roots and treats every
top-level `Title (Year)` folder as a movie. The Library page shows one flat
movie list. The `.env` file only supplies a colon-separated list of roots, and
the application has no concept of a library type or a series.

This feature adds two related capabilities:

1. Operators define **named, typed libraries** in `.env`. A library is either
   a **movie library** or a **series library**. The user picks the active
   library in the UI, and the Library page shows only that library's content.
2. A **series library** contains series folders. A series page lists its
   seasons and episodes. Selecting an episode opens the same detail view and
   the same subtitle actions that a movie has today.

The existing safety contract stays in force: the application never writes to,
moves, or deletes a media file during a scan. Subtitle operations keep their
current trash/backup behavior.

## Glossary

- **Library**: a named filesystem root with a type of `movies` or `series`,
  defined by the operator in `.env`.
- **Movie library**: a library whose direct child folders are movies.
- **Series library**: a library whose direct child folders are series.
- **Series**: a top-level folder inside a series library. The folder name can
  have a year, for example `Pluribus (2025)`, or no year, for example
  `The Looney Tunes`.
- **Season**: a grouping of episodes inside a series. A season usually comes
  from a season folder, for example `Season 01` or `Temporada 2`.
- **Episode**: one playable item inside a series. An episode has an optional
  season number, an optional episode number, and one or more video files.
- **Unnumbered video**: a video inside a series folder that has no reliable
  season or episode number.
- **Episode detail view**: the same screen and action set that a movie detail
  view provides today, applied to one episode.
- **Subtitle action**: upload, edit metadata, delete, detect language, rename,
  extract an embedded track, embed a track, transcribe, and translate.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Define and switch named libraries (Priority: P1)

The operator edits `.env` and defines two libraries: `Movies` of type `movies`
and `Series` of type `series`, each with its own root path. The user opens the
application, sees a library selector, picks `Movies`, and sees only movie
cards. The user picks `Series` and sees only series cards. The selected
library stays selected after a page refresh.

**Why this priority**: Without typed named libraries, the series library has no
place to live and the user cannot choose between movie and series content.

**Independent Test**: Define one movie library and one series library in
`.env`, restart the application, select each library in turn, and confirm that
each Library page shows only items from that library. Reload the page and
confirm that the same library remains selected.

**Acceptance Scenarios**:

1. **Given** a valid `.env` with one `movies` library and one `series` library,
   **When** the user opens the application, **Then** the UI offers both
   libraries by name.
2. **Given** two configured libraries, **When** the user selects a library,
   **Then** the Library page shows only that library's items.
3. **Given** a selected library, **When** the user refreshes or bookmarks the
   page, **Then** the same library is selected.
4. **Given** a `.env` entry with an unknown type or a missing root, **When**
   the application starts, **Then** the invalid entry is not used, the other
   entries still work, and the problem is reported in the application log.
5. **Given** a `.env` that only has the legacy root list, **When** the
   application starts, **Then** the existing movie-only behavior still works.

---

### User Story 2 - Browse a series and open an episode (Priority: P1)

The user selects the `Series` library. The Library page shows one card per
series with the series title, episode count, and subtitle coverage. The user
opens a series and sees its seasons in order, each with an ordered episode
list. The user selects an episode and gets the same detail view and subtitle
actions that a movie provides.

**Why this priority**: This is the requested series workflow. It delivers the
main new user value after library configuration.

**Independent Test**: Scan a series library that contains `SxxExx` episodes in
season folders. Open the series, confirm the episode order, select one
episode, and confirm that upload, edit, delete, detect, extract, embed,
transcribe, and translate are available for that episode.

**Acceptance Scenarios**:

1. **Given** a scanned series library, **When** the user opens the Library
   page, **Then** each series folder appears once with its episode count.
2. **Given** a series with several seasons, **When** the user opens the
   series, **Then** seasons are listed in numeric order and episodes inside a
   season are listed in numeric order.
3. **Given** a series page, **When** the user selects an episode, **Then** the
   episode detail view opens with the same actions as a movie detail view.
4. **Given** an episode detail view, **When** the user uploads or generates a
   subtitle, **Then** the subtitle belongs to that episode only and the file
   name identifies the episode and the language.
5. **Given** an episode with multiple video variants, **When** the user opens
   the episode, **Then** all variants appear under the same episode.

---

### User Story 3 - Keep unnumbered videos reachable (Priority: P2)

A series folder contains videos whose names have no reliable season or
episode number. The user still sees the series and can open each video from a
flat list on the series page. Each unnumbered video opens the same episode
detail view and supports the same subtitle actions.

**Why this priority**: Real libraries contain specials, OVAs, and loosely named
files. Hiding them would make the series view incomplete, but numbered
episodes carry most of the value.

**Independent Test**: Add a series folder with one numbered episode and two
files with no episode marker. Confirm that the numbered episode appears in its
season group and both unnumbered files appear in a separate flat list.

**Acceptance Scenarios**:

1. **Given** a series folder with no year in its name, **When** the library is
   scanned, **Then** the folder still appears as a series.
2. **Given** videos with no reliable episode marker, **When** the user opens
   the series, **Then** those videos appear in an `Other videos` list.
3. **Given** an unnumbered video, **When** the user selects it, **Then** the
   episode detail view opens and subtitle actions are available.

---

### User Story 4 - Scan one library or all libraries (Priority: P2)

The user selects a library and starts a scan. Only that library is scanned.
The user can also scan every configured library in one action.

**Why this priority**: Separate typed libraries make a single global scan less
useful. Scanning only the active library keeps large libraries manageable.

**Independent Test**: Configure two libraries with distinct content. Scan one
library and confirm only its items appear. Then scan all and confirm items
from both libraries appear.

**Acceptance Scenarios**:

1. **Given** two configured libraries, **When** the user scans the active
   library, **Then** only that library's jobs run.
2. **Given** two configured libraries, **When** the user scans all libraries,
   **Then** one job runs for each configured library.
3. **Given** a scan of one library, **When** the scan completes, **Then**
   items in other libraries are unchanged.

---

### Edge Cases

- A library root does not exist or is not readable. The scan fails with a
  clear message, and scans of other libraries are not blocked.
- Two library definitions use the same name. Only one definition is used, and
  the duplicate is reported.
- A series folder is a symlink. The series is scanned through the link, and
  media files are never modified.
- A season folder is a symlink. Its episodes are included.
- A filename contains `S01E02`, `1x15`, `E04`, or a bare number such as
  `015.mp4` or `LT_15.mp4`. The parser selects the strongest available marker.
- A bare number looks like a year or a resolution. The parser must not treat
  `1080p`, `2025`, or similar tokens as episode numbers when a safer marker
  exists.
- An episode marker has no season and the parent folder is a season folder.
  The season comes from the folder.
- An episode marker has no season and the parent folder is not a season
  folder. The episode is listed without a season group.
- Several video files share a season and episode number. They are variants of
  one episode.
- Two different files claim the same season and episode number but have
  different base names. They remain in the same episode group, and each file
  is visible.
- A subtitle filename matches one episode. The subtitle belongs to that
  episode only.
- A subtitle filename matches no episode in a folder with several episodes.
  The application does not assign it to an arbitrary episode.
- A season or episode folder becomes empty. A rescan removes only stale
  database rows, not media files.
- A series title also exists in a movie library. The two items remain
  independent.
- The operator changes a library name or root. The new definition is used
  after restart; existing scan data is not silently reassigned to a different
  library.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The application MUST read named library definitions from `.env`.
  Each definition MUST provide a display name, a type of `movies` or `series`,
  and one filesystem root.
- **FR-002**: The application MUST reject library definitions with an unknown
  type, an empty name, an empty root, or a duplicate name. A rejected
  definition MUST be logged and MUST NOT block valid definitions.
- **FR-003**: The application MUST keep the legacy root list as a valid
  movie-only configuration when no named libraries are defined.
- **FR-004**: The UI MUST show a library selector with every valid configured
  library, including its display name and type.
- **FR-005**: The active library MUST be visible in the page address so that a
  refresh or bookmark restores it.
- **FR-006**: The Library page MUST show only items from the active library.
- **FR-007**: A movie library MUST keep the current behavior: each direct
  child folder that matches `Title (Year)` becomes one movie.
- **FR-008**: A series library MUST treat each direct child folder as one
  series, with or without a year in the folder name.
- **FR-009**: The scanner MUST find video files inside a series folder,
  including files in season subfolders and in symlinked season folders.
- **FR-010**: The scanner MUST extract a season number and an episode number
  from filenames that use `SxxExx`, `NxNN`, `E##`, or a leading bare number.
  It MUST prefer an explicit season/episode marker over a bare number.
- **FR-011**: When a filename has an episode number but no season number, the
  scanner MUST use the season number from a recognized season folder when one
  is present.
- **FR-012**: Video files with the same series, season, and episode number
  MUST appear as one episode with multiple video files.
- **FR-013**: A series page MUST list episodes grouped by season in numeric
  order, and episodes inside each season in numeric order.
- **FR-014**: Videos with no reliable season or episode number MUST appear in
  an `Other videos` list on the series page, and MUST NOT be hidden.
- **FR-015**: Selecting an episode MUST open the same detail view and the same
  subtitle actions that a movie detail view provides.
- **FR-016**: Every subtitle action MUST apply to one episode only. Actions on
  an episode MUST NOT change another episode's subtitles.
- **FR-017**: Generated or uploaded subtitle filenames MUST identify the
  episode and language, and MUST NOT collide between different episodes.
- **FR-018**: When scanning, a subtitle file MUST attach to an episode only
  when its name matches that episode's video name or episode marker. An
  ambiguous subtitle MUST NOT attach to an arbitrary episode.
- **FR-019**: The series list MUST show, per series, the episode count and a
  summary of external and embedded subtitle languages.
- **FR-020**: The user MUST be able to scan the active library. The user MUST
  also be able to scan all configured libraries in one action.
- **FR-021**: A scan MUST NOT create, modify, move, or delete media files.
- **FR-022**: A scan failure in one library MUST NOT prevent a scan of another
  library.
- **FR-023**: Existing movie folders, movie detail views, and movie subtitle
  actions MUST keep their current behavior.
- **FR-024**: Existing scan data MUST remain visible after the upgrade. A
  rescan MAY assign that data to its configured library.
- **FR-025**: The application MUST expose the series, season, and episode
  identity on the episode detail view so the user knows which episode they
  are editing.

### Key Entities *(include if data involved)*

- **Library**: display name, type (`movies` or `series`), filesystem root, and
  a stable identity derived from the configuration.
- **Series**: title, optional year, source folder, parent library, and scan
  time.
- **Episode**: parent series, optional season number, optional episode number,
  display label, one or more video files, and its own external and embedded
  subtitles.
- **Movie**: unchanged identity for a movie-library item, with the addition of
  its parent library.
- **Subtitle**: unchanged file and language metadata, attached to exactly one
  movie or one episode.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can switch between two configured libraries in two
  interactions or fewer, and the Library page shows zero items from the
  inactive library.
- **SC-002**: 100% of valid named libraries in the configuration appear in the
  selector after restart.
- **SC-003**: For the supplied `/jefflix` series fixtures with recognized
  naming, 100% of numbered episodes appear under the correct season and
  episode number in a dry-run scan.
- **SC-004**: Every video file under a scanned series library appears exactly
  once in the series UI, either as part of a numbered episode or in `Other
  videos`.
- **SC-005**: Clicking an episode exposes all subtitle actions that are
  available for a movie in the same build.
- **SC-006**: A dry-run scan of the supplied series libraries writes zero
  bytes inside the library tree.
- **SC-007**: The existing automated test suite passes after the change.

## Assumptions

- The operator edits `.env` and restarts the application to apply library
  changes. The UI does not manage library definitions.
- Each named library has exactly one root. A root that contains both movies
  and series is split into separate movie and series libraries.
- Library type is explicit. The application does not auto-detect a library
  type.
- A series year comes from the series folder name. An episode does not have
  its own year.
- Episode titles are not fetched from an external metadata service. The UI
  shows the season/episode marker and the video file name.
- Unnumbered video files are treated as individual episodes without a season
  or episode number.
- Subtitle files that cannot be matched to one episode are left unassigned
  until a later scan can match them.
- Multi-episode files such as `S01E01-E02` are not part of this feature; the
  parser may treat the first marker as the episode.
- The current safety contract for trash, backups, and protected video files
  does not change.
