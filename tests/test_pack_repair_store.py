"""Unit tests for headless Pack Repair store and state slice."""

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.ui.features.pack_repair.state import PackRepairState
from src.ui.features.pack_repair.store import PackRepairStore
from src.workspace.health import HealthIssue, IssueSeverity, PackHealthReport


def test_no_qt_imports():
    """Verify that state and store have ZERO Qt dependencies."""
    pkg_dir = Path(__file__).parents[1] / "src" / "ui" / "features" / "pack_repair"
    for py_file in (pkg_dir / "state.py", pkg_dir / "store.py"):
        if not py_file.is_file():
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("PySide"), (
                        f"Qt import {alias.name} in {py_file.name}"
                    )
                    assert not alias.name.startswith("PyQt"), (
                        f"Qt import {alias.name} in {py_file.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert not node.module.startswith("PySide"), (
                        f"Qt import {node.module} in {py_file.name}"
                    )
                    assert not node.module.startswith("PyQt"), (
                        f"Qt import {node.module} in {py_file.name}"
                    )


def test_pack_repair_store_initialization():
    issue = HealthIssue(
        issue_id="issue_1",
        file_path="audio/global_music.bnk",
        object_id=247391427,
        title="Word-Swapped Clip Automation Count",
        description="Causes CTD during battle music transition",
        severity=IssueSeverity.CRITICAL_CRASH,
        can_autofix=True,
        fix_description="Re-serialize to canonical count = 1",
    )
    report = PackHealthReport(
        pack_name="custom_music.pack",
        issues=(issue,),
        has_critical_issues=True,
        all_fixable=True,
    )

    store = PackRepairStore(report)
    state = store.state
    assert state.pack_name == "custom_music.pack"
    assert len(state.items) == 1
    assert state.items[0].is_selected is True
    assert state.items[0].fix_description == "Re-serialize to canonical count = 1"
    assert state.can_autofix_any is True
    assert state.selected_count == 1
    assert store.get_selected_issue_ids() == {"issue_1"}


def test_pack_repair_store_toggle_and_select_all():
    issue1 = HealthIssue("i1", "f1", None, "T1", "D1", IssueSeverity.WARNING, True, "Fix 1")
    issue2 = HealthIssue("i2", "f2", None, "T2", "D2", IssueSeverity.CRITICAL_CRASH, True, "Fix 2")
    report = PackHealthReport("mod.pack", (issue1, issue2), True, True)

    store = PackRepairStore(report)
    assert store.state.selected_count == 2

    store.toggle_item("i1")
    assert store.get_selected_issue_ids() == {"i2"}
    assert store.state.selected_count == 1

    store.select_all(False)
    assert len(store.get_selected_issue_ids()) == 0
    assert store.state.selected_count == 0

    store.select_all(True)
    assert store.get_selected_issue_ids() == {"i1", "i2"}
    assert store.state.selected_count == 2


def test_pack_repair_store_immutability():
    issue = HealthIssue("i1", "f1", None, "T1", "D1", IssueSeverity.WARNING, True, "Fix 1")
    report = PackHealthReport("mod.pack", (issue,), False, True)
    store = PackRepairStore(report)

    with pytest.raises(FrozenInstanceError):
        store.state.pack_name = "mutated.pack"  # type: ignore

    with pytest.raises(FrozenInstanceError):
        store.state.items[0].is_selected = False  # type: ignore


def test_pack_repair_store_subscribers():
    issue = HealthIssue("i1", "f1", None, "T1", "D1", IssueSeverity.WARNING, True, "Fix 1")
    report = PackHealthReport("mod.pack", (issue,), False, True)
    store = PackRepairStore(report)

    received: list[PackRepairState] = []
    store.subscribe(lambda s: received.append(s))

    store.toggle_item("i1")
    assert len(received) == 1
    assert received[-1].items[0].is_selected is False

    store.select_all(True)
    assert len(received) == 2
    assert received[-1].items[0].is_selected is True


def test_pack_repair_store_unfixable_issues():
    fixable = HealthIssue("i1", "f1", None, "T1", "D1", IssueSeverity.WARNING, True, "Fix 1")
    unfixable = HealthIssue("i2", "f2", None, "T2", "D2", IssueSeverity.CRITICAL_CRASH, False, None)
    report = PackHealthReport("mod.pack", (fixable, unfixable), True, False)

    store = PackRepairStore(report)
    # Only fixable should be selected initially
    assert store.get_selected_issue_ids() == {"i1"}
    assert store.state.selected_count == 1
    assert store.state.can_autofix_any is True

    # Attempting to toggle unfixable item must not select it
    store.toggle_item("i2")
    assert store.get_selected_issue_ids() == {"i1"}

    # select_all(True) must only select fixable items
    store.select_all(True)
    assert store.get_selected_issue_ids() == {"i1"}
    assert store.state.selected_count == 1


def test_pack_repair_store_empty_report():
    report = PackHealthReport("clean.pack", ())
    store = PackRepairStore(report)
    assert store.state.pack_name == "clean.pack"
    assert len(store.state.items) == 0
    assert store.state.can_autofix_any is False
    assert store.state.selected_count == 0
    assert store.get_selected_issue_ids() == set()

    store.toggle_item("nonexistent")
    assert store.state.selected_count == 0
    store.select_all(True)
    assert store.state.selected_count == 0
