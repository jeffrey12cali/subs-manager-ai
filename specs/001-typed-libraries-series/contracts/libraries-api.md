# Contract: Libraries API

**Feature**: [spec.md](../spec.md) | **Data model**: [data-model.md](../data-model.md)

## GET /libraries

Returns every valid configured library in `.env` order.

Response `200`:

```json
[
  {
    "id": "movies",
    "name": "Movies",
    "type": "movies",
    "root": "/jefflix/Movies"
  },
  {
    "id": "series",
    "name": "Series",
    "type": "series",
    "root": "/jefflix/Series"
  }
]
```

Errors:

- `200` with `[]` when no library is configured.

Notes:

- An invalid or duplicate `.env` entry is absent from the response and is
  written to the application log.
- The legacy `LIBRARY_ROOTS` configuration appears as one or more `movies`
  libraries when `LIBRARIES` is empty.

## POST /library/scan

Starts a scan for one library or for every configured library.

Query parameters:

| Name | Type | Required | Meaning |
|------|------|----------|---------|
| `library` | string | no | Configured library ID. Omit to scan all libraries. |

Response `200`:

```json
{
  "job_ids": [41, 42],
  "roots": ["/jefflix/Movies", "/jefflix/Series"]
}
```

Errors:

- `404` when `library` is not a configured ID.
- `400` when no library is configured.
- `200` with one failed job per inaccessible root is allowed; the response
  still lists the created job IDs.

Notes:

- The legacy `GET/POST/DELETE /library/roots` routes keep their current
  behavior.
- The scan is read-only for the library tree.

## GET /library/roots

Unchanged legacy route. Returns database roots used only when neither
`LIBRARIES` nor `LIBRARY_ROOTS` is configured.
