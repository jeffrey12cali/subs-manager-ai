from datetime import datetime

import pytest

from app.core.policy import (
    APP_OWNED_SUB_SOURCES,
    PROTECTED_SUB_SOURCES,
    PolicyViolation,
    assert_can_delete_sub,
    can_delete_sub,
    can_overwrite_existing_sub,
)
from app.models import ExternalSubtitle, SubSource


def _sub(source: SubSource) -> ExternalSubtitle:
    return ExternalSubtitle(
        movie_id=1,
        path="/library/X/X.srt",
        real_path="/library/X/X.srt",
        filename="X.srt",
        source=source,
        created_at=datetime.utcnow(),
    )


def test_protected_set_has_preexisting():
    assert SubSource.preexisting in PROTECTED_SUB_SOURCES


def test_app_owned_set_has_generators():
    for s in (
        SubSource.whisper,
        SubSource.translated,
        SubSource.extracted,
        SubSource.manual,
    ):
        assert s in APP_OWNED_SUB_SOURCES


def test_protected_and_app_owned_are_disjoint():
    assert PROTECTED_SUB_SOURCES.isdisjoint(APP_OWNED_SUB_SOURCES)


def test_preexisting_cannot_be_deleted():
    assert can_delete_sub(_sub(SubSource.preexisting)) is False
    with pytest.raises(PolicyViolation):
        assert_can_delete_sub(_sub(SubSource.preexisting))


@pytest.mark.parametrize(
    "source",
    [SubSource.whisper, SubSource.translated, SubSource.extracted, SubSource.manual],
)
def test_app_owned_can_be_deleted(source: SubSource):
    assert can_delete_sub(_sub(source)) is True
    assert_can_delete_sub(_sub(source))  # no raise


def test_uploads_never_silent_overwrite():
    assert can_overwrite_existing_sub() is False
