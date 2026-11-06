"""Presentation menu widgets for multi-select and checkable dropdowns.

Provides CheckableMenu which keeps popup menus open when toggling checkable actions.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QMenu


class CheckableMenu(QMenu):
    """QMenu that stays open when checkable actions are toggled.

    Standard Qt QMenu dismisses whenever any action is clicked or activated.
    For multi-select configuration dropdowns (such as column visibility and overlay
    pickers), this forces users to repeatedly re-open the dropdown for each selection.
    CheckableMenu intercepts click and space events on checkable items to toggle them
    in-place while preserving popup visibility.
    """

    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if self.rect().contains(pos):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        action = self.actionAt(pos)
        if action is not None:
            if action.isCheckable() and action.menu() is None:
                if action.isEnabled():
                    action.trigger()
                event.accept()
                return
            if action.menu() is None:
                if action.isEnabled():
                    action.trigger()
                self.close()
                event.accept()
                return
            super().mouseReleaseEvent(event)
            return

        if self.rect().contains(pos):
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Space:
            active = self.activeAction()
            if active is not None and active.isCheckable() and active.menu() is None:
                if active.isEnabled():
                    active.trigger()
                event.accept()
                return
        super().keyPressEvent(event)
