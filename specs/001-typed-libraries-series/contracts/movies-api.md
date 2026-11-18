# Contract: Movies and Episode Detail API

**Feature**: [spec.md](../spec.md) | **Data model**: [data-model.md](../data-model.md)

## GET /movies/

Lists movie-library items. Episodes are never returned by this route.

Query parameters:

| Name | Type | Required | Meaning |
|------|------|----------|---------|
| `library` | string | no | Configured `movies` library ID. |
| `missing_subs` | boolean | no | Only items with no external or embedded subtitles. |

Response `200`: `MovieSummary[]`.

Each item has the existing fields plus:

```json
{
  "id": 12,
  "title": "Stalker",
  "year": 1979,
  "folder_path": "/jefflix/Movies/Stalker (1979)",
  "kind": "movie",
  "library_id": "movies",
  "season_number": null,
  "episode_number": null,
  "episode_label": null,
  "video_count": 1,
  "external_sub_count": 2,
  "external_sub_languages": ["en", "ru"],
  "unknown_sub_count": 0,
  "embedded_sub_count": 0,
  "embedded_sub_languages": [],
  "has_subs": true,
  "video_formats": ["mkv"],
  "subtitle_formats": ["srt"]
}
```

Errors:

- `404` when `library` is not a configured ID.
- `422` when `library` is a `series` library.

Compatibility:

- Rows with `library_id = null` (created before the upgrade) match a library
  when their `folder_path` is inside that library root.

## GET /movies/{movie_id}

Returns the movie detail payload or the episode detail payload. The frontend
uses this route for both `/movies/:id` and `/episodes/:id`.

Response `200`:

```json
{
  "id": 812,
  "folder_path": "/jefflix/Series/Pluribus (2025)#Season 01S01E02",
  "title": "Pluribus",
  "year": 2025,
  "kind": "episode",
  "library_id": "series",
  "series_id": 7,
  "series_title": "Pluribus",
  "season_number": 1,
  "episode_number": 2,
  "episode_label": "S01E02",
  "scanned_at": "2026-11-17T20:00:00Z",
  "video_files": [
    {
      "id": 900,
      "movie_id": 812,
      "path": "/jefflix/Series/Pluribus (2025)/Season 01/Pluribus S01E02.mkv",
      "real_path": "/jefflix/Raw/Pluribus [HDTV 1080p][Cap.102]/Pluribus [HDTV 1080p][Cap.102].mkv",
      "is_symlink": true,
      "filename": "Pluribus S01E02.mkv",
      "variant": null,
      "size": 1234,
      "mtime": "2026-11-01T10:00:00Z",
      "hash": "abc",
      "container": "mkv",
      "duration": 3120.0,
      "video_codec": "h264",
      "audio_tracks": [],
      "embedded_subs": []
    }
  ],
  "external_subs": []
}
```

Errors:

- `404` when the ID does not exist.

Compatibility:

- `folder_path` for an episode is an identity string, not a real directory.
  The UI shows the series folder from the series page and the video file names
  on the episode page.
- All subtitle routes that take a `movie_id` accept an episode ID:
  upload, translate, and the video-file extract/embed/transcribe routes.

## Subtitle sidecar naming

Every subtitle output path uses:

```text
<subtitle_dir>/<subtitle_stem>.<language>[.forced][.sdh][.<tag>].<ext>
```

Fallbacks for rows created before this feature:

- `subtitle_dir = folder_path`
- `subtitle_stem = "Title (Year)"` or `"Title"`

Episode examples:

```text
Pluribus S01E02.en.srt
Pluribus S01E02.es.forced.srt
Doraemon S01E0001.es.forced.srt
LT_15.en.srt
```

Movie examples stay unchanged:

```text
Stalker (1979).en.srt
Stalker (1979).ru.forced.srt
```
