"""Child widgets for the Audio Sources dock."""

from src.ui.features.audio_sources.widgets.catalog_model import (
    AudioCatalogTableModel,
    AudioCatalogTableView,
)
from src.ui.features.audio_sources.widgets.enhance_tab import EnhanceTab
from src.ui.features.audio_sources.widgets.files_table import FilesTableWidget
from src.ui.features.audio_sources.widgets.game_audio_tab import GameAudioTab
from src.ui.features.audio_sources.widgets.libraries_table import LibrariesTableWidget

__all__ = [
    "AudioCatalogTableModel",
    "AudioCatalogTableView",
    "EnhanceTab",
    "FilesTableWidget",
    "GameAudioTab",
    "LibrariesTableWidget",
]
