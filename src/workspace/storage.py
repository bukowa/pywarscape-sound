from pathlib import Path

from src.workspace.cache import GameCache
from src.workspace.game import GameType
from src.workspace.manifest import ProjectManifest
from src.workspace.project import AudioProject


class ProjectStorage:
    """Manages creation, loading, and atomic persistence of living AudioProject directories."""

    @staticmethod
    def create_project(
        location: Path | str,
        name: str,
        game: GameType | str = GameType.ATTILA,
        author: str = "Modder",
        cache: GameCache | None = None,
    ) -> AudioProject:
        loc = Path(location)
        loc.mkdir(parents=True, exist_ok=True)
        (loc / "pack_root" / "audio").mkdir(parents=True, exist_ok=True)
        (loc / "source_audio").mkdir(parents=True, exist_ok=True)
        (loc / "db").mkdir(parents=True, exist_ok=True)
        (loc / "scripts" / "data").mkdir(parents=True, exist_ok=True)

        readme_file = loc / "scripts" / "README.md"
        if not readme_file.exists():
            readme_file.write_text(
                "# Project Scripts\n\n"
                "Place custom Python automation scripts (*.py) in this directory.\n"
                "Input data tables and CSV files belong in `scripts/data/`.\n",
                encoding="utf-8",
            )

        gt = GameType(game) if isinstance(game, str) else game
        manifest = ProjectManifest(
            name=name,
            game=gt,
            author=author,
        )

        project = AudioProject(root_dir=loc, manifest=manifest, cache=cache)
        ProjectStorage.save_project(project)
        return project

    @staticmethod
    def open_project(location: Path | str, cache: GameCache | None = None) -> AudioProject:
        loc = Path(location)
        manifest_file = loc / "project.json"
        if not manifest_file.is_file():
            raise FileNotFoundError(f"Project manifest not found at {manifest_file}")

        manifest = ProjectManifest.from_json(manifest_file.read_text(encoding="utf-8"))
        project = AudioProject(root_dir=loc, manifest=manifest, cache=cache)
        project.reconcile_manifest_with_disk()
        return project

    @staticmethod
    def save_project(project: AudioProject) -> None:
        """Atomically saves project.json using a temporary file replacement."""
        project.root_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = project.manifest_path
        tmp_path = project.root_dir / "project.json.tmp"

        text = project.manifest.to_json(indent=2)
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(manifest_path)
