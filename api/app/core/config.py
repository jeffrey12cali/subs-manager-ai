import logging
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

LIBRARY_TYPES = frozenset({"movies", "series"})


@dataclass(frozen=True)
class LibraryConfig:
    id: str
    name: str
    type: str
    root: str


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "library"


def _parse_libraries(raw: str) -> list[LibraryConfig]:
    """Parse `Name|type|/root;Name|type|/root` into valid library entries."""
    libraries: list[LibraryConfig] = []
    seen: set[str] = set()
    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        parts = [p.strip() for p in entry.split("|")]
        if len(parts) != 3:
            log.warning("ignoring library entry %r: expected name|type|root", entry)
            continue
        name, lib_type, root = parts
        if not name or not root:
            log.warning("ignoring library entry %r: empty name or root", entry)
            continue
        if lib_type.lower() not in LIBRARY_TYPES:
            log.warning("ignoring library entry %r: unknown type %r", entry, lib_type)
            continue
        lib_id = _slugify(name)
        if lib_id in seen:
            log.warning("ignoring library entry %r: duplicate id %r", entry, lib_id)
            continue
        seen.add(lib_id)
        libraries.append(
            LibraryConfig(id=lib_id, name=name, type=lib_type.lower(), root=root)
        )
    return libraries


def _legacy_libraries(paths: list[str]) -> list[LibraryConfig]:
    libraries: list[LibraryConfig] = []
    seen: set[str] = set()
    for path in paths:
        name = Path(path).name or "Library"
        lib_id = _slugify(name)
        suffix = 2
        while lib_id in seen:
            lib_id = f"{_slugify(name)}-{suffix}"
            suffix += 1
        seen.add(lib_id)
        libraries.append(
            LibraryConfig(id=lib_id, name=name, type="movies", root=path)
        )
    return libraries


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Library
    libraries: str = ""
    library_roots: str = "/library"
    # Extra paths the safe-fs write gate should allow (e.g. symlink targets
    # outside the scanned library) without being scanned themselves.
    safe_fs_roots: str = ""

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"

    # Storage
    database_url: str = "sqlite:////data/subs.db"
    data_dir: str = "/data"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Whisper
    whisper_model: str = "small"
    whisper_compute_type: str = "int8"
    whisper_vad: bool = True

    # Translator
    deepseek_api_key: str = ""
    openai_base_url: str = "https://api.deepseek.com/v1"
    translate_model: str = "deepseek-chat"

    @property
    def library_root_paths(self) -> list[str]:
        return [p for p in self.library_roots.split(":") if p]

    @property
    def safe_fs_root_paths(self) -> list[str]:
        return [p for p in self.safe_fs_roots.split(":") if p]

    @property
    def configured_libraries(self) -> list[LibraryConfig]:
        if self.libraries.strip():
            return _parse_libraries(self.libraries)
        return _legacy_libraries(self.library_root_paths)

    @property
    def writable_roots(self) -> list[str]:
        roots = [lib.root for lib in self.configured_libraries]
        roots += self.library_root_paths
        return list(dict.fromkeys(roots))

    def get_library(self, library_id: str) -> LibraryConfig | None:
        return next(
            (lib for lib in self.configured_libraries if lib.id == library_id),
            None,
        )


settings = Settings()
