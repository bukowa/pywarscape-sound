"""Headless state store for the Project Wizard feature slice."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from src.ui.features.project_wizard.causation import reconcile_project_wizard
from src.ui.features.project_wizard.state import (
    ModPackEntry,
    ProjectWizardEvent,
    ProjectWizardState,
    WizardGameValidationUpdated,
    WizardImportDbTablesToggled,
    WizardModPackAdded,
    WizardModPackMoved,
    WizardModPackRemoved,
    WizardProjectLocationUpdated,
    WizardProjectNameUpdated,
    WizardStatusMessageSet,
    WizardStep,
    WizardStepTransitionRequested,
    WizardWorkProgressUpdated,
)
from src.workspace.cache import GameCache
from src.workspace.dependencies import DependencyManager
from src.workspace.game import GameType
from src.workspace.game_detector import GameDetector
from src.workspace.project import AudioProject
from src.workspace.storage import ProjectStorage


class ProjectWizardStore:
    """Headless observable store managing multi-step project onboarding and dependency ingestion."""

    def __init__(
        self,
        initial_game: GameType | str = GameType.ATTILA,
        default_location: str | None = None,
    ) -> None:
        gt = GameType(initial_game) if isinstance(initial_game, str) else initial_game
        self._subscribers: list[Callable[[ProjectWizardState], None]] = []
        loc = (
            str(default_location).strip()
            if default_location is not None and str(default_location).strip()
            else str(Path.cwd() / "projects")
        )
        avail, msg = self._check_target_availability("MyAudioMod", loc)
        self._state = ProjectWizardState(
            selected_game=gt,
            project_location=loc,
            is_target_dir_available=avail,
            target_dir_validation_msg=msg,
        )
        # Attempt auto-detection for initial game
        self._detect_and_validate(gt)

    @staticmethod
    def _check_target_availability(name: str, loc: str) -> tuple[bool, str]:
        name_str, loc_str = name.strip(), loc.strip()
        if not name_str or not loc_str:
            return True, ""
        dest = Path(loc_str) / name_str
        if dest.exists():
            return False, f"Project folder already exists: {dest.name}"
        return True, ""

    @property
    def state(self) -> ProjectWizardState:
        """Current immutable snapshot of the Project Wizard state."""
        return self._state

    def subscribe(self, callback: Callable[[ProjectWizardState], None]) -> None:
        """Register a state listener invoked on every mutation."""
        self._subscribers.append(callback)

    def _dispatch(self, event: ProjectWizardEvent) -> None:
        """Pure state evolution and subscriber notification."""
        new_state, _intents = reconcile_project_wizard(self._state, event)
        if new_state != self._state:
            self._state = new_state
            for callback in list(self._subscribers):
                callback(self._state)

    def set_selected_game(self, game: GameType | str) -> None:
        """Update selected game engine and trigger auto-detection."""
        gt = GameType(game) if isinstance(game, str) else game
        self._dispatch(
            WizardGameValidationUpdated(
                selected_game=gt,
                game_path=self._state.game_path,
                is_game_path_valid=self._state.is_game_path_valid,
                game_path_validation_msg=self._state.game_path_validation_msg,
                is_cache_valid=self._state.is_cache_valid,
            )
        )
        self._detect_and_validate(gt)

    def set_game(self, game: GameType | str) -> None:
        """Convenience alias for set_selected_game."""
        self.set_selected_game(game)

    def set_game_path(self, path_str: str) -> None:
        """Update game installation directory and run validation."""
        clean_path = path_str.strip()
        if not clean_path:
            self._dispatch(
                WizardGameValidationUpdated(
                    selected_game=self._state.selected_game,
                    game_path="",
                    is_game_path_valid=False,
                    game_path_validation_msg="Path is empty",
                    is_cache_valid=False,
                )
            )
            return

        valid, msg = GameDetector.validate_game_dir(self._state.selected_game, clean_path)
        cache_valid = False
        if valid:
            cache = GameCache(self._state.selected_game)
            cache_valid = cache.is_valid()

        self._dispatch(
            WizardGameValidationUpdated(
                selected_game=self._state.selected_game,
                game_path=clean_path,
                is_game_path_valid=valid,
                game_path_validation_msg=msg,
                is_cache_valid=cache_valid,
            )
        )

    def set_project_name(self, name: str) -> None:
        """Update project name."""
        avail, msg = self._check_target_availability(name, self._state.project_location)
        self._dispatch(
            WizardProjectNameUpdated(
                project_name=name,
                is_target_dir_available=avail,
                target_dir_validation_msg=msg,
            )
        )

    def set_project_location(self, loc: Path | str) -> None:
        """Update workspace location directory."""
        loc_str = str(loc)
        avail, msg = self._check_target_availability(self._state.project_name, loc_str)
        self._dispatch(
            WizardProjectLocationUpdated(
                project_location=loc_str,
                is_target_dir_available=avail,
                target_dir_validation_msg=msg,
            )
        )

    def set_import_db_tables(self, enabled: bool) -> None:
        """Toggle audio-linked database tables ingestion."""
        self._dispatch(WizardImportDbTablesToggled(enabled=enabled))

    def add_mod_pack(
        self,
        pack_path: Path | str,
        repaired_files: dict[str, bytes] | tuple[tuple[str, bytes], ...] | None = None,
    ) -> bool:
        """Validate and append an external .pack dependency with optional pre-repaired payloads."""
        clean = str(pack_path).strip()
        p = Path(clean)
        if not p.is_file() or not p.name.lower().endswith(".pack"):
            self._dispatch(WizardStatusMessageSet(status_message=f"Invalid .pack file: {clean}"))
            return False

        # Reject duplicates by resolved path or filename
        resolved = str(p.resolve())
        norm_name = p.name.lower()
        for existing in self._state.mod_packs:
            if (
                existing.filename.lower() == norm_name
                or str(Path(existing.path).resolve()) == resolved
            ):
                self._dispatch(
                    WizardStatusMessageSet(status_message=f"Mod pack already added: {p.name}")
                )
                return False

        repaired_tuple: tuple[tuple[str, bytes], ...] = ()
        if repaired_files:
            if isinstance(repaired_files, dict):
                repaired_tuple = tuple(repaired_files.items())
            else:
                repaired_tuple = tuple(repaired_files)

        entry = ModPackEntry(
            path=resolved,
            filename=p.name,
            size_bytes=p.stat().st_size,
            repaired_files=repaired_tuple,
        )
        self._dispatch(WizardModPackAdded(entry=entry))
        return True

    def remove_mod_pack(self, index: int) -> bool:
        """Remove a mod pack at given index."""
        prev_len = len(self._state.mod_packs)
        self._dispatch(WizardModPackRemoved(index=index))
        return len(self._state.mod_packs) < prev_len

    def move_mod_pack(self, index: int, direction: int) -> bool:
        """Reorder mod pack (-1 for UP, +1 for DOWN)."""
        prev_packs = self._state.mod_packs
        self._dispatch(WizardModPackMoved(index=index, direction=direction))
        return self._state.mod_packs != prev_packs

    def go_to_step(self, step: WizardStep) -> bool:
        """Transition wizard to a given step with validation."""
        self._dispatch(WizardStepTransitionRequested(step=step))
        return self._state.step == step

    def build_cache(self, progress_cb: Callable[[str, float], None] | None = None) -> bool:
        """Extract vanilla soundbanks and event database from game packs into cache."""
        if not self._state.is_game_path_valid:
            self._dispatch(
                WizardStatusMessageSet(
                    status_message="Cannot build cache: game directory is invalid"
                )
            )
            return False

        try:
            self._dispatch(
                WizardWorkProgressUpdated(
                    step=self._state.step,
                    is_working=True,
                    progress_percentage=0.0,
                    progress_text="Building game cache...",
                )
            )
            cache = GameCache(self._state.selected_game)
            data_dir = Path(self._state.game_path) / "data"
            cache.extract_from_game_packs(data_dir, progress_cb=progress_cb)
            cache_valid = cache.is_valid()
            self._dispatch(
                WizardWorkProgressUpdated(
                    step=self._state.step,
                    is_working=False,
                    progress_percentage=1.0 if cache_valid else 0.0,
                    progress_text="Cache built successfully"
                    if cache_valid
                    else "Failed to build cache",
                    is_cache_valid=cache_valid,
                )
            )
            return cache_valid
        except Exception as e:
            self._dispatch(
                WizardWorkProgressUpdated(
                    step=self._state.step,
                    is_working=False,
                    progress_percentage=0.0,
                    progress_text="",
                    status_message=f"Cache extraction failed: {e}",
                )
            )
            return False

    def create_project_and_ingest(
        self,
        progress_cb: Callable[[str, float], None] | None = None,
    ) -> AudioProject | None:
        """Create project on disk and ingest parent mod packs in priority order."""
        name = self._state.project_name.strip()
        loc = self._state.project_location.strip()
        if not name or not loc or not self._state.is_target_dir_available:
            self._dispatch(
                WizardStatusMessageSet(
                    status_message=self._state.target_dir_validation_msg
                    or "Project name and location are required"
                )
            )
            return None

        try:
            self._dispatch(
                WizardWorkProgressUpdated(
                    step=WizardStep.PROGRESS,
                    is_working=True,
                    progress_percentage=0.0,
                    progress_text="Creating project structure...",
                )
            )
            dest_dir = Path(loc) / name
            project = ProjectStorage.create_project(
                location=dest_dir,
                name=name,
                game=self._state.selected_game,
            )

            # Ingest mod packs if specified
            if self._state.mod_packs:
                dep_mgr = DependencyManager(project)
                total = len(self._state.mod_packs)
                for idx, entry in enumerate(self._state.mod_packs):
                    desc = f"Importing {entry.filename}..."
                    pct = idx / total
                    self._dispatch(
                        WizardWorkProgressUpdated(
                            step=WizardStep.PROGRESS,
                            is_working=True,
                            progress_percentage=pct,
                            progress_text=desc,
                        )
                    )
                    if progress_cb:
                        progress_cb(desc, pct)

                    plan = dep_mgr.plan_import(entry.path, priority=idx)
                    dep_mgr.execute_import(plan)

                    # Write any pre-repaired bank payloads directly into dependency storage
                    dep_dir = project.get_dependency_dir(plan.pack_name)
                    for vpath, repaired_bytes in dict(entry.repaired_files).items():
                        norm_vpath = vpath.replace("\\", "/")
                        if not norm_vpath.startswith("audio/"):
                            norm_vpath = f"audio/{norm_vpath}"
                        dest = dep_dir / norm_vpath
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(repaired_bytes)

                    done_pct = (idx + 1) / total
                    done_desc = f"Imported {entry.filename} ({idx + 1}/{total})"
                    self._dispatch(
                        WizardWorkProgressUpdated(
                            step=WizardStep.PROGRESS,
                            is_working=True,
                            progress_percentage=done_pct,
                            progress_text=done_desc,
                        )
                    )
                    if progress_cb:
                        progress_cb(done_desc, done_pct)

                ProjectStorage.save_project(project)

            self._dispatch(
                WizardWorkProgressUpdated(
                    step=WizardStep.PROGRESS,
                    is_working=False,
                    progress_percentage=1.0,
                    progress_text="Project created successfully",
                    created_project=project,
                    status_message=None,
                )
            )
            return project
        except Exception as e:
            self._dispatch(
                WizardWorkProgressUpdated(
                    step=WizardStep.PROGRESS,
                    is_working=False,
                    progress_percentage=0.0,
                    progress_text="",
                    status_message=f"Project creation failed: {e}",
                )
            )
            return None

    def skip_to_finish(self) -> AudioProject | None:
        """Bypass mod pack ingestion and immediately create a vanilla project."""
        name = self._state.project_name.strip()
        loc = self._state.project_location.strip()
        if not name or not loc or not self._state.is_target_dir_available:
            self._dispatch(
                WizardStatusMessageSet(
                    status_message=self._state.target_dir_validation_msg
                    or "Project name and location are required"
                )
            )
            return None

        try:
            dest_dir = Path(loc) / name
            project = ProjectStorage.create_project(
                location=dest_dir,
                name=name,
                game=self._state.selected_game,
            )
            self._dispatch(
                WizardWorkProgressUpdated(
                    step=WizardStep.PROGRESS,
                    is_working=False,
                    progress_percentage=1.0,
                    progress_text="Vanilla project created",
                    created_project=project,
                    status_message=None,
                )
            )
            return project
        except Exception as e:
            self._dispatch(
                WizardWorkProgressUpdated(
                    step=WizardStep.PROGRESS,
                    is_working=False,
                    progress_percentage=0.0,
                    progress_text="",
                    status_message=f"Project creation failed: {e}",
                )
            )
            return None

    def _detect_and_validate(self, game_type: GameType) -> None:
        detected = GameDetector.detect_game_install(game_type)
        if detected is not None:
            self.set_game_path(str(detected))
        else:
            cache = GameCache(game_type)
            self._dispatch(
                WizardGameValidationUpdated(
                    selected_game=game_type,
                    game_path="",
                    is_game_path_valid=False,
                    game_path_validation_msg="Not detected automatically",
                    is_cache_valid=cache.is_valid(),
                )
            )

    def _update_state(self, **kwargs) -> None:
        if "mod_packs" in kwargs and not isinstance(kwargs["mod_packs"], tuple):
            kwargs["mod_packs"] = tuple(kwargs["mod_packs"])
        self._state = replace(self._state, **kwargs)
        for callback in list(self._subscribers):
            callback(self._state)
