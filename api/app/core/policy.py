"""Domain-level destruction policy.

Pure functions only — no IO. Use these from API handlers and worker tasks
so the rules are testable and consistent.
"""

from __future__ import annotations

from app.models import ExternalSubtitle, SubSource

# Subs the app DID NOT create. Treated as user-owned data.
# We never destroy these; user must remove them outside the app if they
# really want them gone.
PROTECTED_SUB_SOURCES: frozenset[SubSource] = frozenset({SubSource.preexisting})

# Subs the app generated and is therefore allowed to clean up via trash().
APP_OWNED_SUB_SOURCES: frozenset[SubSource] = frozenset(
    {SubSource.whisper, SubSource.translated, SubSource.extracted, SubSource.manual}
)


class PolicyViolation(Exception):
    """Raised when an action would violate the destruction policy."""


def can_delete_sub(sub: ExternalSubtitle) -> bool:
    """Whether the API may move this sub to trash."""
    return sub.source not in PROTECTED_SUB_SOURCES


def assert_can_delete_sub(sub: ExternalSubtitle) -> None:
    if not can_delete_sub(sub):
        raise PolicyViolation(
            f"sub id={sub.id} is {sub.source.value!r} (preexisting on disk before "
            "the app touched it). Refusing to delete; remove it manually if "
            "you really want it gone."
        )


def can_overwrite_existing_sub() -> bool:
    """Uploads never silently overwrite. Caller must explicitly opt in
    via `force=true`, and even then we route through trash() not unlink."""
    return False
