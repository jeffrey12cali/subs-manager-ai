# Data Model: Typed Libraries and Series Browsing

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

## Overview

The database keeps `Movie` as the single media-item table. A movie row is
either a movie (`kind = movie`) or an episode (`kind = episode`). A `Series`
row groups episode rows. Existing video, subtitle, embedded-track, and job
rows keep their `movie_id` foreign keys, so all current actions continue to
work.

Configured libraries are read from `.env`; they are not stored in a table.
`Movie.library_id` and `Series.library_id` store the configured identity.

## Configuration Model (not stored)

### Library definition

Parsed from `LIBRARIES`. One entry is `name|type|root`.

| Field | Type | Rules |
|-------|------|-------|
| `name` | string | Non-empty after trim. May contain spaces. Must not contain `|` or `;`. Unique after ID derivation. |
| `type` | enum | `movies` or `series`. Any other value rejects the entry. |
| `root` | string | Non-empty absolute path after trim. May not exist at configuration time. Must not contain `;`. |
| `id` | string | Derived: lowercase name, runs of non-alphanumeric replaced with `-`, trimmed. Used in URLs and stored IDs. |

Definitions are validated in `.env` order. The first definition that claims an
`id` wins. Later duplicates are skipped and logged.

When `LIBRARIES` is empty, each path in `LIBRARY_ROOTS` becomes a `movies`
library. The ID comes from the root basename; if that collides, append
`-<n>`.

## Stored Entities

### Series

| Field | Type | Rules |
|-------|------|-------|
| `id` | integer | Primary key. |
| `library_id` | string | Indexed. Parent configured library. |
| `folder_path` | string | Unique, indexed. Lexical path of the series folder. |
| `title` | string | Folder name with a trailing ` (YYYY)` removed. |
| `year` | integer or null | Parsed from the folder name. |
| `scanned_at` | datetime or null | Last successful series scan. |

Relationships:

- One series has many episodes (`Movie` rows with `kind = episode`).
- A series cannot be shared between libraries.

### Movie (movie or episode item)

Existing fields stay. New fields:

| Field | Type | Rules |
|-------|------|-------|
| `kind` | enum (`movie`, `episode`) | Non-null, default `movie`. Indexed. |
| `library_id` | string or null | Indexed. Null on rows created before this feature until a rescan. |
| `series_id` | integer or null | Foreign key to `series.id`, indexed. Required when `kind = episode`, null when `kind = movie`. |
| `season_number` | integer or null | Season from the filename or nearest season folder. Null when unknown. |
| `episode_number` | integer or null | Parsed episode number. Null for an unnumbered video. |
| `episode_label` | string or null | `S01E02` for a numbered episode, video stem for an unnumbered video, null for a movie. |
| `subtitle_dir` | string or null | Directory for new sidecar subtitles. Episodes use the episode video's parent. Movies use the movie folder. |
| `subtitle_stem` | string or null | Canonical sidecar stem. Episodes use the primary video stem with a variant suffix removed. Movies use `Title (Year)` or `Title`. |

Identity rules:

- `folder_path` stays unique.
- Movie: `folder_path` is the real movie folder.
- Numbered episode:
  `folder_path = "<series folder>#<relative parent>S<season>E<episode>"`.
  When the season is unknown:
  `folder_path = "<series folder>#<relative parent>E<episode>"`.
- Unnumbered video:
  `folder_path = "<series folder>#<relative video path>"`.
- The `#` value is an identity string. The UI does not display it as a folder.
- Episode `title` is the series title. The episode header uses `series.title`,
  `episode_label`, and the video file name.
- Episode `year` is the series year, for display only. Sidecar names use
  `subtitle_stem` and do not append the year.
- A rescan upserts by `folder_path`; a second scan of the same tree does not
  create duplicates.

Validation:

- `kind = movie` requires a non-null `title` and a real folder path.
- `kind = episode` requires `series_id`, `subtitle_dir`, and `subtitle_stem`.
- `episode_number` without `season_number` is valid. `season_number` without
  `episode_number` is not created; the video stays unnumbered.
- `library_id` for an episode equals its series `library_id`.

### VideoFile

Unchanged. `movie_id` points to a movie or an episode. Several video rows may
belong to one episode when the episode has variants.

### ExternalSubtitle

Unchanged. `movie_id` points to a movie or an episode. `rel_dir` stays
relative to the item's real directory. Subtitle output uses
`Movie.subtitle_dir` and `Movie.subtitle_stem`.

### EmbeddedSubtitle

Unchanged. It belongs to a `VideoFile`, which belongs to a movie or episode.

### Job

Unchanged. `movie_id` points to a movie or an episode.

## Relationship Diagram

```text
Series 1 ─── * Movie (kind=episode)
Movie  1 ─── * VideoFile 1 ─── * EmbeddedSubtitle
Movie  1 ─── * ExternalSubtitle
Movie  1 ─── * Job
```

A `Movie` with `kind = movie` has no `series_id`. A `Movie` with
`kind = episode` always has a `series_id`.

## Library Filtering

- `GET /movies/?library=<id>` returns movies whose `library_id` matches.
- For rows with `library_id = NULL` (before the first post-upgrade scan), the
  API also matches by the configured root prefix of `folder_path`.
- `GET /series/?library=<id>` returns series whose `library_id` matches.
- No library parameter means all movie rows or all series rows, according to
  the endpoint.

## API Read Models

### LibraryRead

```text
id: string
name: string
type: "movies" | "series"
root: string
```

### MovieSummary (extended)

Existing fields plus:

```text
kind: "movie" | "episode"
library_id: string | null
season_number: int | null
episode_number: int | null
episode_label: string | null
```

### MovieDetail (extended)

Existing fields plus:

```text
kind: "movie" | "episode"
library_id: string | null
series_id: int | null
series_title: string | null
season_number: int | null
episode_number: int | null
episode_label: string | null
```

### EpisodeSummary

```text
id: int
title: string
episode_label: string | null
season_number: int | null
episode_number: int | null
video_count: int
external_sub_count: int
external_sub_languages: list[str]
unknown_sub_count: int
embedded_sub_count: int
embedded_sub_languages: list[str]
has_subs: bool
video_formats: list[str]
subtitle_formats: list[str]
```

### SeriesSummary

```text
id: int
library_id: string
title: string
year: int | null
folder_path: string
episode_count: int
video_count: int
external_sub_count: int
external_sub_languages: list[str]
unknown_sub_count: int
embedded_sub_count: int
embedded_sub_languages: list[str]
has_subs: bool
```

### SeriesDetail

```text
id: int
library_id: string
title: str
year: int | null
folder_path: str
scanned_at: datetime | null
season_groups: [
  {
    season_number: int | null,
    episodes: EpisodeSummary[]
  }
]
other_videos: EpisodeSummary[]
```

`season_groups` is sorted by season number, with an unknown season last.
Episodes inside a group are sorted by episode number, then label, then `id`.
`other_videos` is sorted by video file name.

## Migration

Revision `20261117_0002_typed_libraries_series`:

1. Create `series` with a unique `folder_path` index and an indexed
   `library_id`.
2. Add nullable columns to `movie`: `kind` (with server default `movie`),
   `library_id`, `series_id`, `season_number`, `episode_number`,
   `episode_label`, `subtitle_dir`, `subtitle_stem`.
3. Backfill every existing row:
   - `kind = 'movie'`
   - `subtitle_dir = folder_path`
   - `subtitle_stem = Title (Year)` when a year exists, otherwise `Title`
4. Add indexes on `movie.kind`, `movie.library_id`, and `movie.series_id`.
5. Keep the unique `movie.folder_path` constraint.
6. Keep all existing video, subtitle, embedded, and job rows.

Downgrade drops the new indexes, the new columns, and the `series` table. It
does not touch media files.

## Invariants

- A scan writes zero bytes inside a library root.
- A video file belongs to exactly one media item.
- A subtitle belongs to exactly one media item.
- A numbered episode groups all videos with the same series, season, and
  episode number.
- An unnumbered video has its own media item and its own episode detail page.
- An unmatched subtitle stays unassigned and is reported in scan statistics.
- Two scans of the same tree produce the same item IDs and the same episode
  grouping.
