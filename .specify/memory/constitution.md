# subs-manager-ai Constitution

## Core Principles

### I. Media Safety (NON-NEGOTIABLE)

The application must never destroy user media. A scan is read-only for the
library tree. A subtitle deletion moves the file to the trash directory.
An MKV replacement keeps a timestamped backup. No code path may call a raw
unlink on a library file, and no code path may overwrite a video except the
MKV mux flow. Every write must pass the safe-filesystem gate.

### II. Library Fidelity

The scanner must preserve what exists on disk. A media file must appear
exactly once in the UI: as a movie, as a numbered episode, or as an unnumbered
video. A subtitle must attach to one item only when the match is reliable.
The parser must prefer an explicit season/episode marker over a weak guess.
Unsupported layouts must be reported, not silently discarded.

### III. Test-Backed Changes

Backend behavior needs pytest coverage for the changed paths. Parser changes
need table-driven tests with real-world filename examples. API changes need
route tests. Frontend changes must pass the TypeScript build. A bug fix starts
with a test that fails before the fix. The full backend suite must pass before
a change is complete.

### IV. Small, Config-Driven Changes

Configuration belongs in `.env`. New runtime settings must have a safe default
and must be documented in `.env.example`. Prefer the existing models,
scanners, routers, and UI patterns over new abstractions. Do not add a
dependency unless the existing stack cannot solve the problem. Keep the scope
of a change tied to the request.

## Additional Constraints

- The stack is Python 3.11, FastAPI, SQLModel, Alembic, ARQ, React, and
  TypeScript. Use the existing tools in this stack.
- SQLite stores application state. A schema change needs an Alembic migration.
- The library may use absolute symlinks. Resolve real paths for probing and
  writes, and keep the lexical path for display.
- The UI must work on a LAN without accounts. Do not add authentication unless
  the feature requires it.

## Development Workflow

1. Write or update the specification and plan artifacts.
2. Add failing tests for the new behavior.
3. Implement the smallest change that passes the tests.
4. Run `make test-local` or `cd api && uv run pytest` and
   `cd web && npm run build`.
5. For a real-library check, use a temporary database and data directory.
   Never write to the library during validation.

## Governance

This constitution takes priority over code style preferences. A change that
breaks Principle I is rejected. A change that violates another principle must
state why the violation is necessary and what simpler option was rejected.
Amendments require a separate commit that updates this file and its version.

**Version**: 1.0.0 | **Ratified**: 2026-11-17 | **Last Amended**: 2026-11-17
