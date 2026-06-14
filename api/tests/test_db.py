from sqlalchemy import text
from sqlmodel import Session


def test_wal_pragma_applied(engine):
    with Session(engine) as s:
        mode = s.exec(text("PRAGMA journal_mode")).scalar()  # type: ignore[attr-defined]
        assert mode.lower() == "wal"


def test_foreign_keys_enforced(engine):
    with Session(engine) as s:
        fk = s.exec(text("PRAGMA foreign_keys")).scalar()  # type: ignore[attr-defined]
        assert fk == 1


def test_tables_created(engine):
    expected = {
        "movie",
        "videofile",
        "externalsubtitle",
        "embeddedsubtitle",
        "job",
        "libraryroot",
        "setting",
    }
    with Session(engine) as s:
        rows = s.exec(  # type: ignore[attr-defined]
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).all()
    names = {r[0] for r in rows}
    assert expected.issubset(names)
