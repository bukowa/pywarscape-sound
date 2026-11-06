"""Tests for the Pack Health Repair Dialog view."""

import pytest
from PySide6.QtWidgets import QCheckBox, QDialog, QLabel

from src.ui.features.pack_repair.store import PackRepairStore
from src.ui.features.pack_repair.view import PackRepairDialog
from src.workspace.health import HealthIssue, IssueSeverity, PackHealthReport


def test_pack_repair_dialog_rendering_and_actions(qapp):
    issue = HealthIssue(
        issue_id="ca_track_clip_auto_swapped",
        file_path="audio/global_music.bnk",
        object_id=247391427,
        title="Word-Swapped Clip Automation Count",
        description="Causes CTD during dynamic music transition",
        severity=IssueSeverity.CRITICAL_CRASH,
        can_autofix=True,
        fix_description="Re-serialize to canonical count = 1",
    )
    report = PackHealthReport("custom_music.pack", (issue,), True, True)
    store = PackRepairStore(report)
    dialog = PackRepairDialog(store)

    assert (
        "custom_music.pack" in dialog.windowTitle()
        or "custom_music.pack" in dialog.subtitle_label.text()
    )
    assert dialog.fix_button.isEnabled() is True
    assert "Auto-Fix" in dialog.fix_button.text()
    assert dialog.ignore_button.isVisible() is True
    assert dialog.cancel_button.isVisible() is True


def test_pack_repair_dialog_button_clicks(qapp):
    issue = HealthIssue(
        issue_id="ca_track_clip_auto_swapped",
        file_path="audio/global_music.bnk",
        object_id=247391427,
        title="Word-Swapped Clip Automation Count",
        description="Causes CTD",
        severity=IssueSeverity.CRITICAL_CRASH,
        can_autofix=True,
        fix_description="Re-serialize",
    )
    report = PackHealthReport("custom_music.pack", (issue,), True, True)
    store = PackRepairStore(report)

    # Click Auto-Fix accepts dialog
    dialog1 = PackRepairDialog(store)
    dialog1.fix_button.click()
    assert dialog1.result() == QDialog.DialogCode.Accepted

    # Click Ignore proceeds with code 10
    dialog2 = PackRepairDialog(store)
    dialog2.ignore_button.click()
    assert dialog2.result() == 10

    # Click Cancel rejects dialog
    dialog3 = PackRepairDialog(store)
    dialog3.cancel_button.click()
    assert dialog3.result() == QDialog.DialogCode.Rejected


def test_pack_repair_dialog_checkbox_toggling(qapp):
    issue1 = HealthIssue(
        issue_id="issue_1",
        file_path="audio/bank_1.bnk",
        object_id=1001,
        title="Test Issue 1",
        description="Description 1",
        severity=IssueSeverity.WARNING,
        can_autofix=True,
        fix_description="Fix 1",
    )
    issue2 = HealthIssue(
        issue_id="issue_2",
        file_path="audio/bank_2.bnk",
        object_id=1002,
        title="Test Issue 2",
        description="Description 2",
        severity=IssueSeverity.CRITICAL_CRASH,
        can_autofix=False,
        fix_description="",
    )
    report = PackHealthReport("mod.pack", (issue1, issue2), True, False)
    store = PackRepairStore(report)
    dialog = PackRepairDialog(store)

    assert dialog.fix_button.isEnabled() is True
    cb1 = dialog.findChild(QCheckBox, "cb_issue_1")
    cb2 = dialog.findChild(QCheckBox, "cb_issue_2")

    assert cb1 is not None
    assert cb1.isChecked() is True
    assert cb1.isEnabled() is True

    assert cb2 is not None
    assert cb2.isChecked() is False
    assert cb2.isEnabled() is False

    # Uncheck issue 1 -> selected_count drops to 0 -> fix_button disabled
    cb1.click()
    assert store.state.selected_count == 0
    assert dialog.fix_button.isEnabled() is False

    # Check issue 1 again -> fix_button enabled
    cb1.click()
    assert store.state.selected_count == 1
    assert dialog.fix_button.isEnabled() is True


def test_pack_repair_dialog_no_autofix_disables_button(qapp):
    issue = HealthIssue(
        issue_id="unfixable",
        file_path="audio/manual.bnk",
        object_id=999,
        title="Manual Fix Only",
        description="No auto-repair",
        severity=IssueSeverity.WARNING,
        can_autofix=False,
    )
    report = PackHealthReport("mod.pack", (issue,), False, False)
    store = PackRepairStore(report)
    dialog = PackRepairDialog(store)

    assert dialog.fix_button.isEnabled() is False


def test_pack_repair_dialog_store_select_all_updates_view(qapp):
    issue1 = HealthIssue("i1", "p1", 1, "T1", "D1", IssueSeverity.WARNING, True, "Fix 1")
    issue2 = HealthIssue("i2", "p2", 2, "T2", "D2", IssueSeverity.CRITICAL_CRASH, True, "Fix 2")
    report = PackHealthReport("mod.pack", (issue1, issue2), True, True)
    store = PackRepairStore(report)
    dialog = PackRepairDialog(store)

    cb1 = dialog.findChild(QCheckBox, "cb_i1")
    cb2 = dialog.findChild(QCheckBox, "cb_i2")
    assert cb1.isChecked() is True
    assert cb2.isChecked() is True
    assert dialog.fix_button.isEnabled() is True

    # Deselect all via store
    store.select_all(False)
    assert cb1.isChecked() is False
    assert cb2.isChecked() is False
    assert dialog.fix_button.isEnabled() is False

    # Select all via store
    store.select_all(True)
    assert cb1.isChecked() is True
    assert cb2.isChecked() is True
    assert dialog.fix_button.isEnabled() is True


def test_pack_repair_dialog_badges(qapp):
    issue1 = HealthIssue("i1", "p1", 1, "T1", "D1", IssueSeverity.WARNING, True, "Fix 1")
    issue2 = HealthIssue("i2", "p2", 2, "T2", "D2", IssueSeverity.CRITICAL_CRASH, True, "Fix 2")
    report = PackHealthReport("mod.pack", (issue1, issue2), True, True)
    store = PackRepairStore(report)
    dialog = PackRepairDialog(store)

    # Check badge labels exist in the dialog layout
    labels = [lbl.text() for lbl in dialog.findChildren(QLabel)]
    assert "WARNING" in labels
    assert "CRITICAL CTD" in labels
