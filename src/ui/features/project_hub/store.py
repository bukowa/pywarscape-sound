"""Headless state store for the Project Hub feature slice in Audio Editor v3."""

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from src.ui.features.project_hub.causation import reconcile_project_hub
from src.ui.features.project_hub.state import (
    CacheBuildFinished,
    CacheBuildProgressUpdated,
    CacheBuildStarted,
    GamePathEvaluated,
    NewProjectLocationSet,
    NewProjectNameSet,
    ProjectActionFailed,
    ProjectHubEvent,
    ProjectHubState,
    ProjectOpenedSuccessfully,
    RecentProjectItem,
    SelectedGameChanged,
)
from src.workspace.cache import GameCache
from src.workspace.game import GameType
from src.workspace.game_detector import GameDetector
from src.workspace.paths import get_recent_projects_path
from src.workspace.project import AudioProject
from src.workspace.storage import ProjectStorage

_MAX_RECENT_PROJECTS = 10


class ProjectHubStore:
    """Headless observable store managing Project Hub state and workspace actions."""

    def __init__(self, cache_file: Path | None = None) -> None:
        self._cache_file = cache_file if cache_file is not None else get_recent_projects_path()
        self._subscribers: list[Callable[[ProjectHubState], None]] = []
        recent = self._load_recent_projects()
        self._state = ProjectHubState(recent_projects=recent)
        self._detect_and_validate(self._state.selected_game)

    @property
    def state(self) -> ProjectHubState:
        """Current immutable snapshot of the Project Hub state."""
        return self._state

    def subscribe(self, callback: Callable[[ProjectHubState], None]) -> None:
        """Register a state listener invoked whenever state changes."""
        self._subscribers.append(callback)

    def _dispatch(self, event: ProjectHubEvent) -> None:
        """Pure state evolution and subscriber notification."""
        new_state, _intents = reconcile_project_hub(self._state, event)
        if new_state != self._state:
            self._state = new_state
            for callback in list(self._subscribers):
                callback(self._state)

    def set_new_project_name(self, name: str) -> None:
        """Update draft mod project name."""
        self._dispatch(NewProjectNameSet(name=name))

    def set_new_project_location(self, loc: str) -> None:
        """Update draft mod project parent location directory."""
        self._dispatch(NewProjectLocationSet(location=loc))

    def set_selected_game(self, game: GameType | str) -> None:
        """Update target Total War game engine and auto-detect installation."""
        gt = GameType(game) if isinstance(game, str) else game
        self._dispatch(SelectedGameChanged(game=gt))
        self._detect_and_validate(gt)

    def set_game_path(self, path_str: str) -> None:
        """Update game installation directory and run validation."""
        clean_path = path_str.strip()
        cache = GameCache(self._state.selected_game)
        cache_valid = cache.is_valid()
        cache_msg = self._format_cache_status(cache, cache_valid)

        if not clean_path:
            self._dispatch(
                GamePathEvaluated(
                    game_path="",
                    is_game_path_valid=False,
                    game_path_validation_msg="Path is empty",
                    is_cache_valid=cache_valid,
                    cache_status_msg=cache_msg,
                )
            )
            return

        valid, msg = GameDetector.validate_game_dir(self._state.selected_game, clean_path)
        self._dispatch(
            GamePathEvaluated(
                game_path=clean_path,
                is_game_path_valid=valid,
                game_path_validation_msg=msg,
                is_cache_valid=cache_valid,
                cache_status_msg=cache_msg,
            )
        )

    def build_cache(self, progress_cb: Callable[[str, float], None] | None = None) -> bool:
        """Extract vanilla soundbanks and event database from game packs into cache."""
        if not self._state.is_game_path_valid:
            self._dispatch(
                ProjectActionFailed(status_message="Cannot build cache: game directory is invalid")
            )
            return False

        try:
            self._dispatch(CacheBuildStarted())
            cache = GameCache(self._state.selected_game)
            data_dir = Path(self._state.game_path) / "data"

            def wrapped_cb(pack_name: str, pct: float) -> None:
                self._dispatch(
                    CacheBuildProgressUpdated(
                        progress_text=f"Extracting {pack_name}...",
                        progress_percentage=pct,
                    )
                )
                if progress_cb is not None:
                    progress_cb(pack_name, pct)

            cache.extract_from_game_packs(data_dir, progress_cb=wrapped_cb)
            cache_valid = cache.is_valid()
            status = self._format_cache_status(cache, cache_valid)
            self._dispatch(
                CacheBuildFinished(
                    is_cache_valid=cache_valid,
                    cache_status_msg=status,
                )
            )
            return cache_valid
        except Exception as e:
            self._dispatch(
                CacheBuildFinished(
                    is_cache_valid=False,
                    cache_status_msg="",
                    error_message=f"Cache extraction failed: {e}",
                )
            )
            return False

    def open_project_by_path(self, path_str: str) -> AudioProject | None:
        """Open an existing project from disk, gating on game cache readiness."""
        try:
            target = Path(path_str)
            project = ProjectStorage.open_project(target)
            if not project.cache.is_valid():
                game_type = project.manifest.game
                game_name = game_type.value if hasattr(game_type, "value") else str(game_type)
                self.set_selected_game(game_type)
                self._dispatch(
                    ProjectActionFailed(
                        status_message=f"Cannot open project '{project.manifest.name}': {game_name.title()} game cache is not built. Please configure game directory and build cache below."
                    )
                )
                return None

            resolved_path = str(target.resolve())
            game_val = (
                project.manifest.game.value
                if hasattr(project.manifest.game, "value")
                else str(project.manifest.game)
            )
            recent = self._add_recent_project(
                name=project.manifest.name,
                path_str=resolved_path,
                game=game_val,
            )
            self._dispatch(
                ProjectOpenedSuccessfully(
                    recent_projects=recent,
                    loaded_project_path=resolved_path,
                )
            )
            self._save_cache()
            return project
        except Exception as e:
            self._dispatch(ProjectActionFailed(status_message=f"Failed to open project: {e}"))
            return None

    def open_existing_project(self, path_str: str) -> AudioProject | None:
        """Alias for open_project_by_path for opening projects and updating recent history."""
        return self.open_project_by_path(path_str)

    def create_project(self) -> AudioProject | None:
        """Create a new mod project directory and manifest, updating recent history."""
        name = self._state.new_project_name.strip()
        if not name:
            self._dispatch(ProjectActionFailed(status_message="Project name cannot be empty"))
            return None

        location = self._state.new_project_location.strip()
        if not location:
            self._dispatch(ProjectActionFailed(status_message="Project location cannot be empty"))
            return None

        try:
            dest_dir = Path(location) / name
            project = ProjectStorage.create_project(
                location=dest_dir,
                name=name,
                game=self._state.selected_game,
            )
            resolved_path = str(dest_dir.resolve())
            recent = self._add_recent_project(
                name=name,
                path_str=resolved_path,
                game=self._state.selected_game.value,
            )
            self._dispatch(
                ProjectOpenedSuccessfully(
                    recent_projects=recent,
                    loaded_project_path=resolved_path,
                )
            )
            self._save_cache()
            return project
        except Exception as e:
            self._dispatch(ProjectActionFailed(status_message=f"Failed to create project: {e}"))
            return None

    def _detect_and_validate(self, game_type: GameType) -> None:
        detected = GameDetector.detect_game_install(game_type)
        if detected is not None:
            self.set_game_path(str(detected))
        else:
            cache = GameCache(game_type)
            cache_valid = cache.is_valid()
            self._dispatch(
                GamePathEvaluated(
                    game_path="",
                    is_game_path_valid=False,
                    game_path_validation_msg="Not detected automatically",
                    is_cache_valid=cache_valid,
                    cache_status_msg=self._format_cache_status(cache, cache_valid),
                )
            )

    def _format_cache_status(self, cache: GameCache, is_valid: bool) -> str:
        if is_valid:
            bank_count = len(cache.list_banks())
            return f"Cache Ready ({bank_count} SoundBanks, event_data.dat)"
        return "Game Cache: Not Built"

    def _update_state(self, **kwargs) -> None:
        if "recent_projects" in kwargs and not isinstance(kwargs["recent_projects"], tuple):
            kwargs["recent_projects"] = tuple(kwargs["recent_projects"])
        self._state = replace(self._state, **kwargs)
        for callback in list(self._subscribers):
            callback(self._state)

    def _add_recent_project(
        self, name: str, path_str: str, game: str
    ) -> tuple[RecentProjectItem, ...]:
        resolved = str(Path(path_str).resolve())
        now_iso = datetime.now(UTC).isoformat()
        new_item = RecentProjectItem(
            name=name,
            path=resolved,
            game=game,
            last_opened=now_iso,
        )
        updated = [new_item]
        for item in self._state.recent_projects:
            try:
                if Path(item.path).resolve() != Path(resolved).resolve():
                    updated.append(item)
            except (OSError, ValueError):
                pass
        return tuple(updated[:_MAX_RECENT_PROJECTS])

    def _load_recent_projects(self) -> tuple[RecentProjectItem, ...]:
        if not self._cache_file:
            return ()
        try:
            if not self._cache_file.is_file():
                return ()
            content = self._cache_file.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, dict) and "recent_projects" in data:
                data = data["recent_projects"]
            if not isinstance(data, list):
                return ()

            items: list[RecentProjectItem] = []
            seen_paths = set()
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                path_val = entry.get("path")
                name_val = entry.get("name")
                game_val = entry.get("game", GameType.ATTILA.value)
                last_opened_val = entry.get("last_opened", "")

                if not path_val or not name_val:
                    continue
                try:
                    p = Path(path_val).resolve()
                    if not p.is_dir():
                        continue
                    norm_path = str(p)
                except (OSError, ValueError):
                    continue

                if norm_path in seen_paths:
                    continue
                seen_paths.add(norm_path)

                items.append(
                    RecentProjectItem(
                        name=str(name_val),
                        path=norm_path,
                        game=str(game_val),
                        last_opened=str(last_opened_val),
                    )
                )
                if len(items) >= _MAX_RECENT_PROJECTS:
                    break
            return tuple(items)
        except (OSError, ValueError, json.JSONDecodeError):
            return ()

    def _save_cache(self) -> None:
        if not self._cache_file:
            return
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            payload = [
                {
                    "name": item.name,
                    "path": item.path,
                    "game": item.game,
                    "last_opened": item.last_opened,
                }
                for item in self._state.recent_projects
            ]
            self._cache_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except (OSError, ValueError, TypeError):
            pass
