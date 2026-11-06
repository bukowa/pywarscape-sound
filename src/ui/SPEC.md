# src/ui
Top-level presentation layer (Layer 4).
Hosts centralized dark theme tokens and coordinates all desktop UI feature slices and windows.
- `__init__.py`: UI layer root package namespace (`SafeApplication`, `setup_logging`, `resolve_log_file_path`).
- `columns.py`: Shared headless table column specification and pure audio formatting helpers (`TableColumnSpec`, `format_duration_ms`, `format_sample_rate_khz`, `format_channel_label`).
- `log.py`: Application-wide rotating file logging, `SafeApplication` event boundary, sys.excepthook, threading.excepthook, and Qt message interception (`SafeApplication`, `setup_logging`, `resolve_log_file_path`, `teardown_logging`).
- `menu.py`: Reusable presentation menu widgets (`CheckableMenu` keeping multi-select dropdowns open during item toggles).
- `theme.py`: Centralized design system defining high-contrast dark color tokens (`COLOR_BG_BASE`, `COLOR_TEXT_PRIMARY`), reusable stylesheet definitions (`BTN_STYLE_PRIMARY`, `BTN_STYLE_SECONDARY`, `BTN_STYLE_PRESET`, `CHECKBOX_STYLE`, `INPUT_STYLE`), and `apply_theme` application-wide styling.
- View rules: wrap programmatic widget updates in `blockSignals(True/False)`; preserve scroll position and multi-selection on refresh.
- Tables over 200 rows: `QTableView` + `QAbstractTableModel` with interactive columns.
