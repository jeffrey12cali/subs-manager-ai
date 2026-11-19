from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.core import config
from app.core.config import LibraryConfig
from app.schemas import LibraryRead

router = APIRouter()


@router.get("", response_model=list[LibraryRead])
@router.get("/", response_model=list[LibraryRead])
def list_libraries():
    return [
        LibraryRead(id=lib.id, name=lib.name, type=lib.type, root=lib.root)
        for lib in config.settings.configured_libraries
    ]


def resolve_library(
    library_id: str,
    expected_type: str | None = None,
) -> LibraryConfig:
    library = config.settings.get_library(library_id)
    if library is None:
        raise HTTPException(404, f"Library {library_id!r} not found")
    if expected_type is not None and library.type != expected_type:
        raise HTTPException(
            422,
            f"Library {library.id!r} is {library.type!r}, not {expected_type!r}",
        )
    return library


def path_in_library(library: LibraryConfig, folder_path: str) -> bool:
    path = Path(folder_path)
    root = Path(library.root)
    try:
        path.relative_to(root)
        return True
    except ValueError:
        pass
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True
