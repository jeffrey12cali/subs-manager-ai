# Contract: Series API

**Feature**: [spec.md](../spec.md) | **Data model**: [data-model.md](../data-model.md)

## GET /series/

Lists series for one library or for all libraries.

Query parameters:

| Name | Type | Required | Meaning |
|------|------|----------|---------|
| `library` | string | no | Configured `series` library ID. |

Response `200`: `SeriesSummary[]`.

```json
[
  {
    "id": 7,
    "library_id": "series",
    "title": "Pluribus",
    "year": 2025,
    "folder_path": "/jefflix/Series/Pluribus (2025)",
    "episode_count": 2,
    "video_count": 2,
    "external_sub_count": 1,
    "external_sub_languages": ["en"],
    "unknown_sub_count": 0,
    "embedded_sub_count": 0,
    "embedded_sub_languages": [],
    "has_subs": true
  }
]
```

Sorting: title case-insensitive, then year descending, then ID.

Errors:

- `404` when `library` is not a configured ID.
- `422` when `library` is a `movies` library.

## GET /series/{series_id}

Returns the series detail with season groups and unnumbered videos.

Response `200`:

```json
{
  "id": 7,
  "library_id": "series",
  "title": "Pluribus",
  "year": 2025,
  "folder_path": "/jefflix/Series/Pluribus (2025)",
  "scanned_at": "2026-11-17T20:00:00Z",
  "season_groups": [
    {
      "season_number": 1,
      "episodes": [
        {
          "id": 811,
          "title": "Pluribus",
          "episode_label": "S01E01",
          "season_number": 1,
          "episode_number": 1,
          "video_count": 1,
          "external_sub_count": 0,
          "external_sub_languages": [],
          "unknown_sub_count": 0,
          "embedded_sub_count": 1,
          "embedded_sub_languages": ["en"],
          "has_subs": true,
          "video_formats": ["mkv"],
          "subtitle_formats": ["srt"]
        }
      ]
    }
  ],
  "other_videos": [
    {
      "id": 820,
      "title": "The Looney Tunes",
      "episode_label": "LT_15",
      "season_number": null,
      "episode_number": null,
      "video_count": 1,
      "external_sub_count": 0,
      "external_sub_languages": [],
      "unknown_sub_count": 0,
      "embedded_sub_count": 0,
      "embedded_sub_languages": [],
      "has_subs": false,
      "video_formats": ["mp4"],
      "subtitle_formats": []
    }
  ]
}
```

Rules:

- `season_groups` is sorted by `season_number`. A group with
  `season_number = null` comes last.
- Episodes inside a group are sorted by `episode_number`, then
  `episode_label`, then `id`.
- A numbered episode with no season appears in the `season_number = null`
  group.
- `other_videos` contains only items with `episode_number = null`. It is
  sorted by the primary video filename.
- `episode_count` and `video_count` include `other_videos`.

Errors:

- `404` when the series ID does not exist.

## Episode Detail

There is no separate episode detail route. Use `GET /movies/{episode_id}`
from [movies-api.md](./movies-api.md). The frontend route `/episodes/:id`
renders the movie detail component and uses the same client call.

## Scan

There is no series-specific scan route. Use
`POST /library/scan?library=<series-library-id>` from
[libraries-api.md](./libraries-api.md).
