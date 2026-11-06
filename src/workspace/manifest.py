import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.workspace.game import GameType

SCHEMA_VERSION: str = "1.0"


def _validate_relative_posix(rel_path: str) -> str:
    # Check for drive letters, colons, or leading slashes
    if ":" in rel_path or rel_path.startswith("/") or rel_path.startswith("\\"):
        raise ValueError(
            f"Source audio path must be a relative path without leading slash or drive letter: {rel_path!r}"
        )
    posix_norm = rel_path.replace("\\", "/").strip("/")
    parts = posix_norm.split("/")
    if any(p in (".", "..") for p in parts):
        raise ValueError(f"Source audio path cannot contain parent traversal (..): {rel_path!r}")
    return posix_norm


@dataclass(slots=True)
class DependencyPackInfo:
    """Metadata for an ingested external parent or dependency .pack file."""

    name: str
    source_path: str = ""
    priority: int = 0
    imported_at: str = ""
    sha256: str = ""
    extracted_audio_files: list[str] = field(default_factory=list)
    extracted_db_tables: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.priority = int(self.priority)
        self.extracted_audio_files = list(self.extracted_audio_files)
        self.extracted_db_tables = list(self.extracted_db_tables)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source_path": self.source_path,
            "priority": self.priority,
            "imported_at": self.imported_at,
            "sha256": self.sha256,
            "extracted_audio_files": list(self.extracted_audio_files),
            "extracted_db_tables": list(self.extracted_db_tables),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DependencyPackInfo":
        return cls(
            name=data.get("name", ""),
            source_path=data.get("source_path", ""),
            priority=int(data.get("priority", 0)),
            imported_at=data.get("imported_at", ""),
            sha256=data.get("sha256", ""),
            extracted_audio_files=list(data.get("extracted_audio_files", [])),
            extracted_db_tables=list(data.get("extracted_db_tables", [])),
        )


@dataclass(frozen=True, slots=True)
class SoundLibraryRef:
    """Reference to an external or project-relative sound library folder."""

    id: str
    name: str
    path: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError(f"Sound library id must be a non-empty string, got {self.id!r}")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError(f"Sound library name must be a non-empty string, got {self.name!r}")
        if not isinstance(self.path, str) or not self.path.strip():
            raise ValueError(f"Sound library path must be a non-empty string, got {self.path!r}")

        posix_norm = self.path.replace("\\", "/")
        parts = posix_norm.split("/")
        if any(p == ".." for p in parts):
            raise ValueError(
                f"Sound library path cannot contain parent traversal (..): {self.path!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SoundLibraryRef":
        id_val = data.get("id")
        name_val = data.get("name")
        path_val = data.get("path")
        return cls(
            id="" if id_val is None else str(id_val),
            name="" if name_val is None else str(name_val),
            path="" if path_val is None else str(path_val),
        )


@dataclass(slots=True)
class ProjectManifest:
    """Canonical, portable project manifest for Audio Editor (schema 1.0)."""

    name: str
    game: GameType = GameType.ATTILA
    author: str = "Modder"
    description: str = ""
    version: str = "1.0.0"
    schema_version: str = SCHEMA_VERSION
    modified_banks: list[str] = field(default_factory=list)
    staged_wems: list[int] = field(default_factory=list)
    source_audio: dict[int, str] = field(default_factory=dict)
    custom_names: dict[str, dict[int, str]] = field(default_factory=dict)
    has_custom_event_db: bool = False
    staged_db_tables: list[str] = field(default_factory=list)
    dependencies: list[DependencyPackInfo] = field(default_factory=list)
    sound_libraries: list[SoundLibraryRef] = field(default_factory=list)
    output_pack_path: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.game, str) and not isinstance(self.game, GameType):
            self.game = GameType(self.game)

        # Validate source audio paths
        norm_source: dict[int, str] = {}
        for k, v in self.source_audio.items():
            norm_k = int(k)
            norm_v = _validate_relative_posix(str(v))
            norm_source[norm_k] = norm_v
        self.source_audio = norm_source

        # Normalize staged_wems to ints
        self.staged_wems = [int(w) for w in self.staged_wems]

        # Normalize custom names
        norm_custom: dict[str, dict[int, str]] = {}
        for bank, aliases in self.custom_names.items():
            norm_custom[bank] = {int(k): str(v) for k, v in aliases.items()}
        self.custom_names = norm_custom

        # Normalize dependencies
        norm_deps: list[DependencyPackInfo] = []
        for d in self.dependencies:
            if isinstance(d, dict):
                norm_deps.append(DependencyPackInfo.from_dict(d))
            elif isinstance(d, DependencyPackInfo):
                norm_deps.append(d)
            else:
                raise TypeError(f"Expected DependencyPackInfo or dict, got {type(d)}")
        self.dependencies = norm_deps

        # Normalize sound libraries
        norm_libs: list[SoundLibraryRef] = []
        for lib in self.sound_libraries:
            if isinstance(lib, dict):
                norm_libs.append(SoundLibraryRef.from_dict(lib))
            elif isinstance(lib, SoundLibraryRef):
                norm_libs.append(lib)
            else:
                raise TypeError(f"Expected SoundLibraryRef or dict, got {type(lib)}")
        self.sound_libraries = norm_libs

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "game": self.game.value,
            "author": self.author,
            "description": self.description,
            "version": self.version,
            "modified_banks": sorted(list(set(self.modified_banks))),
            "staged_wems": sorted(list(set(self.staged_wems))),
            "source_audio": {str(k): v for k, v in sorted(self.source_audio.items())},
            "custom_names": {
                bank: {str(k): v for k, v in sorted(aliases.items())}
                for bank, aliases in sorted(self.custom_names.items())
            },
            "has_custom_event_db": self.has_custom_event_db,
            "staged_db_tables": sorted(list(set(self.staged_db_tables))),
            "dependencies": [d.to_dict() for d in self.dependencies],
            "sound_libraries": [lib.to_dict() for lib in self.sound_libraries],
            "output_pack_path": self.output_pack_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectManifest":
        schema_ver = data.get("schema_version", SCHEMA_VERSION)
        raw_game = data.get("game", GameType.ATTILA.value)
        game = GameType(raw_game) if raw_game in GameType._value2member_map_ else GameType.ATTILA

        raw_source = data.get("source_audio", {})
        source_audio = {int(k): v for k, v in raw_source.items()}

        raw_custom = data.get("custom_names", {})
        custom_names = {
            bank: {int(k): str(v) for k, v in aliases.items()}
            for bank, aliases in raw_custom.items()
        }

        raw_deps = data.get("dependencies", [])
        dependencies = [
            DependencyPackInfo.from_dict(d) if isinstance(d, dict) else d for d in raw_deps
        ]

        raw_libs = data.get("sound_libraries", [])
        sound_libraries = [
            SoundLibraryRef.from_dict(lib) if isinstance(lib, dict) else lib for lib in raw_libs
        ]

        return cls(
            name=data.get("name", "Untitled"),
            game=game,
            author=data.get("author", "Modder"),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            schema_version=schema_ver,
            modified_banks=list(data.get("modified_banks", [])),
            staged_wems=[int(w) for w in data.get("staged_wems", [])],
            source_audio=source_audio,
            custom_names=custom_names,
            has_custom_event_db=bool(data.get("has_custom_event_db", False)),
            staged_db_tables=list(data.get("staged_db_tables", [])),
            dependencies=dependencies,
            sound_libraries=sound_libraries,
            output_pack_path=data.get("output_pack_path"),
        )

    def save(self, path: Path | str) -> None:
        """Serializes manifest to JSON file on disk."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json(indent=2), encoding="utf-8")

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, text: str) -> "ProjectManifest":
        return cls.from_dict(json.loads(text))
