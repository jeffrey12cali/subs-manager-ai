# Fixes & Improvements Plan

Six targeted issues. Each entry below has: **diagnosis** (what's wrong and
why), **fix** (what to change), **files** (what to edit), **tests** (what to
add or update). Nothing in this plan is executed until you approve it.

---

## 1. Show "UN" chip for subs without a language label

### Diagnosis
`MovieSummary.external_sub_languages` is built with
`sorted({s.language for s in ext_subs if s.language})` — subs whose
`language` is `NULL` are dropped from the list. The card then sees an
empty `languages` array and renders the red `no subs` text, even though
sidecar files exist on disk.

### Fix
- Add `unknown_sub_count: int` to `MovieSummary` (count of external subs
  with `language IS NULL`).
- In `SubBadges`, when `unknownCount > 0` render a single "UN" chip in a
  warning colour (yellow/amber) alongside the language chips.
- The "no subs" red label only shows when *both* external sub count is
  zero **and** embedded count is zero.

### Files
- `api/app/schemas.py` — add `unknown_sub_count` field.
- `api/app/api/movies.py` — populate it in `list_movies`.
- `web/src/api/client.ts` — add the field to `MovieSummary` interface.
- `web/src/components/LangBadge.tsx` — extend `SubBadges` props.
- `web/src/pages/Library.tsx` — pass the new prop.

### Tests
- `tests/test_movies_api.py` — new test: movie with one `language=None`
  external sub returns `unknown_sub_count == 1`, `external_sub_languages`
  is empty list.

---

## 2. Show embedded tracks as individual language chips

### Diagnosis
`SubBadges` currently shows `+N embedded` as a single blue pill — you
can't see *which* languages are embedded. Also no visual cue that an
individual chip represents an embedded track vs. an external one.

### Fix
- Add `embedded_sub_languages: list[str]` to `MovieSummary`.
- Render each embedded language as its own chip in blue
  (`bg-blue-900 text-blue-200`), with a small "📦" or "M" suffix inside
  the chip to mark it as embedded (e.g. `EN ᴇ` or just a different shape).
- External chips stay neutral grey as today.
- Drop the `+N embedded` aggregate pill.
- Edge case: a language present both externally and embedded shows two
  chips (one neutral, one blue). That's intentional — they're different
  files.

### Files
- `api/app/schemas.py` — add `embedded_sub_languages`.
- `api/app/api/movies.py` — populate it.
- `web/src/api/client.ts` — add field to `MovieSummary`.
- `web/src/components/LangBadge.tsx` — add `variant: "external" | "embedded"`
  prop to `LangBadge`; rewrite `SubBadges` to take both lists.
- `web/src/pages/Library.tsx` — pass the new prop.

### Tests
- `tests/test_movies_api.py` — new test: a movie with one MKV embedding
  `en` and `de` tracks reports `embedded_sub_languages == ["de", "en"]`.

---

## 3. Jobs page "Finished" column is always "2 hours ago"

### Diagnosis
`datetime.utcnow()` is used everywhere on the backend; it returns a
**naive** datetime with no `tzinfo`. When FastAPI serialises it to JSON
it emits an ISO string **without** the trailing `Z` (e.g.
`"2026-05-05T12:34:56.789012"` instead of `"2026-05-05T12:34:56.789012Z"`).
The browser's `new Date(iso)` then parses it as **local time**, and the
diff against `Date.now()` is exactly the user's UTC offset — 2 hours for
CET/CEST. Symptom: every "finished" cell shows "2h ago".

### Fix (two parts, both required)
1. **Backend** — switch every `datetime.utcnow()` call to
   `datetime.now(timezone.utc)` so the value is timezone-aware.
   FastAPI/Pydantic will then serialise it with the `+00:00` suffix and
   the browser will parse it correctly.
2. **Frontend (defensive)** — in `Jobs.tsx`'s `relTime`, if the input
   string lacks a `Z` or `+`/`-` suffix after the time, append `Z` before
   `new Date(...)` to handle any legacy rows already written naïvely.

### Files
- `api/app/models.py` — `Field(default_factory=lambda: datetime.now(timezone.utc))`
- `api/app/workers/{mkv,transcribe,translate}.py` — replace `datetime.utcnow()`.
- `api/app/api/{subs,video_files,library}.py` — same.
- `api/app/scanner/scanner.py` — same.
- `web/src/pages/Jobs.tsx` — harden `relTime`.

### Tests
- `tests/test_jobs_api.py` — new test: a freshly-created Job's
  `created_at` ISO string ends with `+00:00` (or `Z`).
- The existing 271 tests should keep passing — `datetime.now(tz)` is a
  drop-in for naive comparisons in our code (we never compare across
  timezone boundaries).

---

## 4. LLM returned 49 lines for batch of 50 (translation count mismatch)

### Diagnosis
The LLM occasionally **merges adjacent subtitle entries** (especially
when two consecutive lines are mid-sentence) or collapses a continuation
ellipsis like `Hello...\n...world` into one line. The prompt has no
machine-checkable handle for the LLM to align lines 1:1 with the input.

The response excerpt confirms it: the model sometimes joined two
narrative-flow subtitles into one Spanish sentence, dropping a line.
With a 50-line batch this hit 1 mismatch out of every ~50 tries → ~2%
failure rate per batch.

### Fix
**Switch to numbered envelopes.** Wrap every input line in a sentinel
that contains its 1-based index, and parse the response by extracting
exactly those sentinels in order:

```
[[1]] First subtitle line
[[2]] Second subtitle line ⏎ that has an internal break
[[3]] Third
```

Parsing rules:
- Use a regex `^\[\[(\d+)\]\]\s?(.*)$` per line.
- Build a dict `{index: text}`; if a number is missing, mark that line
  empty (don't fail the whole batch).
- If more than ~10 % of indices are missing, raise so the retry kicks in.
- Strip stray prose/commentary lines that don't match the regex.
- Update the system prompt to demand the `[[N]]` prefix exactly.

Belt-and-braces:
- Lower default `BATCH_SIZE` from 50 → 25 (LLMs are noticeably more
  reliable on smaller batches).
- On count mismatch even after parsing, the existing 3-attempt retry
  already kicks in; if it still fails, split the batch in half and recurse
  once before giving up.

### Files
- `api/app/workers/translate.py` — rewrite `_call_api` payload shape and
  parsing; add `_parse_numbered_response`; lower `BATCH_SIZE`; add
  fallback halving on persistent mismatch.

### Tests
- `tests/test_translate.py` — new tests:
  - `_parse_numbered_response` extracts 50 lines from a clean response.
  - Tolerates stray commentary lines (like "Here's the translation:")
    before the numbered block.
  - Recovers when one line is missing (returns empty string for that
    index).
  - Raises when most indices are missing.
  - End-to-end integration test where the fake LLM returns 49/50 lines —
    the recursive halving fallback succeeds.

---

## 5. Translate embedded MKV tracks

### Diagnosis
Right now translation is only available on `ExternalSubtitle` rows.
Embedded tracks have to be extracted first (manual click), and only then
can the translate button be used on the resulting sidecar. That's two
clicks for one workflow.

### Fix
Add a single new endpoint that chains extract → translate server-side.
Re-embedding is **left as a separate manual action** (via the existing
`POST /video-files/{id}/embed`); doing all three steps automatically
would obscure failures and duplicate logic.

- New endpoint:
  `POST /video-files/{vf_id}/translate-embedded/{track_index}`
  body: `{ target_language, source_language? }`
- Logic in a new worker `app/workers/translate_embedded.py`:
  1. Reuse `extract_sub_track` from `app/workers/mkv.py` to write the
     sidecar (with `custom_tag="extracted"`).
  2. Call `do_translate` on the resulting `ExternalSubtitle` row,
     reusing all the chunked-translation logic.
  3. Return the translated sub's path.
- The single `Job` row tracks both phases; progress 0–50 % during
  extract, 50–100 % during translate (rough — extract is fast).
- Reject codecs that aren't text-based (`pgs`, `vobsub`) with a 422.

### Files
- `api/app/workers/translate_embedded.py` (new).
- `api/app/api/video_files.py` — new endpoint + sync fallback.
- `api/app/workers/queue.py` — register the ARQ task.
- `web/src/api/client.ts` — `translateEmbedded()` helper.
- `web/src/pages/Movie.tsx` — small "→ Translate" control next to each
  embedded track row inside `VideoFileCard` (only for text codecs).

### Tests
- `tests/test_translate_embedded.py` (new) — happy path with mocked
  `extract_sub_track` and `_default_translate`; missing track 404; PGS
  codec 422; runner error marks job failed.
- `tests/test_video_files_api.py` — endpoint validation tests.

---

## 6. `Operation not permitted` on `.srt.tmp.<pid>.<ts>` during translate

### Diagnosis
`safe_fs.atomic_write` does three filesystem ops:
```python
open(tmp, "wb")        # 1. create + write
os.chmod(tmp, 0o644)   # 2. set permissions
os.replace(tmp, target)# 3. atomic rename
```
The error string `[Errno 1] Operation not permitted` is **EPERM**, not
**EACCES**. EPERM at this path almost always means the library is
mounted via **SMB/CIFS or NFS without root_squash** and the filesystem
*refuses to honour* `chmod`/`utime` calls regardless of the caller's
permissions. The `open` and `replace` calls succeed; `chmod` is the one
that throws.

(Plain "permission denied" — wrong owner, mode bits — would be EACCES.)

### Fix
- Make the `chmod` step best-effort: catch `PermissionError` /
  `OSError` with `errno in {EPERM, EACCES, ENOTSUP}`, log a warning, and
  continue. The umask of the worker process already produces sensible
  default permissions; explicit chmod is a polish step, not a
  correctness one.
- Add a regression test that simulates an EPERM on `chmod` and asserts
  the file still ends up at the target path.
- Document the scenario in `README.md` under a "Troubleshooting" section
  so future SMB users know what to expect.

### Files
- `api/app/core/safe_fs.py` — wrap `os.chmod` in try/except with errno
  check.
- `tests/test_safe_fs.py` — new test using `monkeypatch` on `os.chmod` to
  raise `PermissionError`; assert atomic_write still succeeds.
- `README.md` — add troubleshooting note.

---

## Order of execution

Suggest tackling in this order:

1. **#3 (datetime UTC)** — small, mechanical, unblocks correct timestamps
   everywhere.
2. **#6 (chmod EPERM)** — small, unblocks translation on SMB mounts.
3. **#4 (translation line count)** — fixes the most user-visible bug.
4. **#1 + #2 (UN chip + embedded chips)** — cohesive UI change, single
   PR.
5. **#5 (translate embedded)** — biggest scope, build last.

Total estimated test additions: ~12 new tests on top of the existing 271.

---

Reply with **go** (or "go, but skip #N", "do #N first", etc.) when ready
and I'll start executing.
