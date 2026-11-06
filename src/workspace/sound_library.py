import os
from dataclasses import dataclass
from pathlib import Path

from src.workspace.manifest import SoundLibraryRef

SUPPORTED_AUDIO_EXTENSIONS: frozenset[str] = frozenset({".wav", ".mp3", ".ogg", ".flac", ".wem"})


@dataclass(frozen=True, slots=True)
class LibraryFileEntry:
    """Scanned audio file entry inside a sound library."""

    library_id: str
    rel_path: str
    abs_path: Path
    size_bytes: int


def encode_library_path(project_root: Path, chosen_dir: Path) -> str:
    """Encodes library directory path: project-relative POSIX if inside project root, else absolute POSIX."""
    proj_resolved = project_root.resolve()
    target = chosen_dir if chosen_dir.is_absolute() else (proj_resolved / chosen_dir)
    target_resolved = target.resolve()
    try:
        rel = target_resolved.relative_to(proj_resolved)
        if rel == Path(".") or str(rel) == ".":
            raise ValueError("Sound library path cannot be the project root itself")
        return rel.as_posix()
    except ValueError as exc:
        if "cannot be the project root itself" in str(exc):
            raise
        return target_resolved.as_posix()


def resolve_library_root(project_root: Path, ref: SoundLibraryRef) -> Path:
    """Resolves SoundLibraryRef path into an absolute filesystem Path."""
    p = Path(ref.path)
    if p.is_absolute() or (len(ref.path) >= 2 and ref.path[1] == ":" and ref.path[0].isalpha()):
        return p.resolve()
    return (project_root / ref.path).resolve()


def is_library_available(project_root: Path, ref: SoundLibraryRef) -> bool:
    """Returns True if the referenced sound library root directory exists on disk."""
    root = resolve_library_root(project_root, ref)
    return root.is_dir()


def _scan_dir_fast(
    dir_path: str,
    root_path: str,
    ref_id: str,
    entries: list[LibraryFileEntry],
) -> None:
    """Fast recursive directory scanner using os.scandir with zero redundant syscalls."""
    try:
        with os.scandir(dir_path) as it:
            subdirs: list[str] = []
            for entry in it:
                name = entry.name
                if name.startswith("."):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        subdirs.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        dot_idx = name.rfind(".")
                        if dot_idx != -1 and name[dot_idx:].lower() in SUPPORTED_AUDIO_EXTENSIONS:
                            try:
                                size = entry.stat(follow_symlinks=False).st_size
                            except OSError:
                                size = 0
                            rel = os.path.relpath(entry.path, root_path).replace("\\", "/")
                            entries.append(
                                LibraryFileEntry(
                                    library_id=ref_id,
                                    rel_path=rel,
                                    abs_path=Path(entry.path),
                                    size_bytes=size,
                                )
                            )
                except OSError:
                    continue
            for sub in subdirs:
                _scan_dir_fast(sub, root_path, ref_id, entries)
    except OSError:
        pass


def scan_library(project_root: Path, ref: SoundLibraryRef) -> tuple[LibraryFileEntry, ...]:
    """Recursively scans a sound library directory for supported audio files.

    Ignores hidden files and directories (starting with '.').
    Returns an immutable tuple of LibraryFileEntry objects sorted by rel_path ascending.
    If the library directory does not exist, returns an empty tuple gracefully.
    """
    if not is_library_available(project_root, ref):
        return ()

    root = resolve_library_root(project_root, ref)
    root_str = str(root)
    entries: list[LibraryFileEntry] = []
    _scan_dir_fast(root_str, root_str, ref.id, entries)
    entries.sort(key=lambda e: e.rel_path)
    return tuple(entries)
