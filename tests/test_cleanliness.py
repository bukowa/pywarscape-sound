import ast
import re
from pathlib import Path


def test_zero_emoji_icons():
    """Ensure zero AI slop emojis or decorative pictorial symbols in src, tests, scripts, and .agents."""
    repo_root = Path(__file__).resolve().parents[1]
    scan_dirs = [
        repo_root / "src",
        repo_root / "tests",
        repo_root / "scripts",
        repo_root / ".agents",
    ]
    violations = []

    # Matches Unicode emoji pictographs and symbols
    emoji_pattern = re.compile(r"[\U0001F300-\U0001FAFF]|[\u2600-\u27BF]")

    for d in scan_dirs:
        for file_path in sorted(d.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.suffix in (".py", ".md", ".yaml", ".yml", ".json", ".txt"):
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                matches = emoji_pattern.findall(content)
                if matches:
                    violations.append(f"{file_path.relative_to(repo_root)}: {matches}")

    assert not violations, "Found AI slop emojis:\n" + "\n".join(violations)


def test_all_views_no_hardcoded_hex_colors():
    repo_root = Path(__file__).resolve().parents[1]
    ui_dir = repo_root / "src" / "ui"
    violations = []

    for py_path in sorted(ui_dir.rglob("*.py")):
        if py_path.name == "theme.py":
            continue
        content = py_path.read_text(encoding="utf-8")
        matches = re.findall(r"#[0-9a-fA-F]{3,8}\b", content)
        if matches:
            violations.append(f"{py_path.relative_to(repo_root)}: {matches}")

    assert not violations, "Found hardcoded hex colors in UI files:\n" + "\n".join(violations)


def test_all_states_and_stores_zero_qt_imports():
    repo_root = Path(__file__).resolve().parents[1]
    ui_dir = repo_root / "src" / "ui"
    violations = []

    for target_name in ("state.py", "store.py", "coordinator.py", "overlays.py", "columns.py"):
        for py_path in sorted(ui_dir.rglob(target_name)):
            tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith(("PySide", "PyQt")):
                            violations.append(
                                f"{py_path.relative_to(repo_root)} imports {alias.name}"
                            )
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.startswith(("PySide", "PyQt")):
                        violations.append(
                            f"{py_path.relative_to(repo_root)} imports from {node.module}"
                        )

    assert not violations, "Found Qt imports in headless state/store:\n" + "\n".join(violations)


def test_arch_guard_passes_all_src():
    from scripts.arch_guard import check_all_src_files

    repo_root = Path(__file__).resolve().parents[1]
    errors = check_all_src_files(repo_root)
    assert errors == [], "Architecture guard violations found:\n" + "\n".join(errors)


def test_arch_guard_detects_violations(tmp_path: Path):
    from scripts.arch_guard import check_file

    # 1. Bare except in src
    f1 = tmp_path / "src" / "engine" / "bad_except.py"
    f1.parent.mkdir(parents=True, exist_ok=True)
    f1.write_text("try:\n    pass\nexcept:\n    pass\n", encoding="utf-8")
    errs = check_file(f1, repo_root=tmp_path)
    assert any("Bare except" in e for e in errs)

    # 2. Broad exception with single pass
    f2 = tmp_path / "src" / "engine" / "bad_swallow.py"
    f2.write_text("try:\n    pass\nexcept Exception:\n    pass\n", encoding="utf-8")
    errs = check_file(f2, repo_root=tmp_path)
    assert any("Silent exception swallowing" in e for e in errs)

    # 3. Layer import matrix: bnk importing workspace
    f3 = tmp_path / "src" / "bnk" / "bad_imp.py"
    f3.parent.mkdir(parents=True, exist_ok=True)
    f3.write_text("import src.workspace.project\n", encoding="utf-8")
    errs = check_file(f3, repo_root=tmp_path)
    assert any("Forbidden higher-layer import" in e for e in errs)

    # 3b. Layer import matrix: engine importing workspace
    f3b = tmp_path / "src" / "engine" / "bad_imp.py"
    f3b.parent.mkdir(parents=True, exist_ok=True)
    f3b.write_text("import src.workspace.project\n", encoding="utf-8")
    errs = check_file(f3b, repo_root=tmp_path)
    assert any("Forbidden higher-layer import" in e for e in errs)

    # 4. Pure module with default_factory=list
    f4 = tmp_path / "src" / "ui" / "features" / "test" / "state.py"
    f4.parent.mkdir(parents=True, exist_ok=True)
    f4.write_text(
        "from dataclasses import dataclass, field\n@dataclass\nclass Foo:\n    items: list = field(default_factory=list)\n",
        encoding="utf-8",
    )
    errs = check_file(f4, repo_root=tmp_path)
    assert any("Disallowed default_factory=list" in e for e in errs)

    # 5. Causation raising exception
    f5 = tmp_path / "src" / "ui" / "features" / "test" / "causation.py"
    f5.write_text("def decide():\n    raise ValueError('error')\n", encoding="utf-8")
    errs = check_file(f5, repo_root=tmp_path)
    assert any("Causation cannot raise domain exceptions" in e for e in errs)

    # 6. View encapsulation: accessing private store attribute
    f6 = tmp_path / "src" / "ui" / "features" / "test" / "view.py"
    f6.write_text(
        "class MyView:\n    def do_work(self):\n        x = self.store._loaded_banks\n",
        encoding="utf-8",
    )
    errs = check_file(f6, repo_root=tmp_path)
    assert any("View encapsulation violation" in e for e in errs)

    # 7. Table test importing mock
    f7 = tmp_path / "tests" / "test_table_demo.py"
    f7.parent.mkdir(parents=True, exist_ok=True)
    f7.write_text("from unittest.mock import Mock\n", encoding="utf-8")
    errs = check_file(f7, repo_root=tmp_path)
    assert any("Mocking forbidden" in e for e in errs)

    # 8. UI Audio Isolation: dialog/view in src/ui importing pygame
    f8 = tmp_path / "src" / "ui" / "features" / "test" / "dialog.py"
    f8.write_text("import pygame\n", encoding="utf-8")
    errs = check_file(f8, repo_root=tmp_path)
    assert any(
        "Forbidden pygame import in UI layer outside audio_transport/store.py" in e for e in errs
    )

    f8_allowed = tmp_path / "src" / "ui" / "features" / "audio_transport" / "store.py"
    f8_allowed.parent.mkdir(parents=True, exist_ok=True)
    f8_allowed.write_text("import pygame\n", encoding="utf-8")
    errs_allowed = check_file(f8_allowed, repo_root=tmp_path)
    assert not any("Forbidden pygame import" in e for e in errs_allowed)

    # 9. Workspace importing engine
    f9 = tmp_path / "src" / "workspace" / "bad_eng_imp.py"
    f9.parent.mkdir(parents=True, exist_ok=True)
    f9.write_text("import src.engine.session\n", encoding="utf-8")
    errs = check_file(f9, repo_root=tmp_path)
    assert any("Forbidden engine import in workspace" in e for e in errs)

    # 10. PYTEST_CURRENT_TEST in src
    f10 = tmp_path / "src" / "engine" / "bad_pytest_ref.py"
    f10.write_text('import os\nis_test = "PYTEST_CURRENT_TEST" in os.environ\n', encoding="utf-8")
    errs = check_file(f10, repo_root=tmp_path)
    assert any("Reference to 'PYTEST_CURRENT_TEST' forbidden in src" in e for e in errs)

    # 11. Cross-module private import in src
    f11 = tmp_path / "src" / "engine" / "bad_priv_imp.py"
    f11.write_text("from src.engine.ontology import _private_helper\n", encoding="utf-8")
    errs = check_file(f11, repo_root=tmp_path)
    assert any("Cross-module private import forbidden in src" in e for e in errs)

    # 12. Duplicate qapp fixture in tests/
    f12 = tmp_path / "tests" / "test_dup_qapp.py"
    f12.parent.mkdir(parents=True, exist_ok=True)
    f12.write_text("import pytest\n@pytest.fixture\ndef qapp():\n    pass\n", encoding="utf-8")
    errs = check_file(f12, repo_root=tmp_path)
    assert any("Duplicate qapp fixture forbidden in tests" in e for e in errs)


def test_arch_guard_detects_incomplete_feature_slice(tmp_path: Path):
    from scripts.arch_guard import check_all_src_files

    slice_dir = tmp_path / "src" / "ui" / "features" / "incomplete_slice"
    slice_dir.mkdir(parents=True, exist_ok=True)
    (slice_dir / "state.py").write_text("# state\n", encoding="utf-8")

    errs = check_all_src_files(tmp_path)
    assert any("Feature slice missing SPEC.md" in e for e in errs)
    assert any("Feature slice missing causation.py" in e for e in errs)
    assert any("Feature slice missing store.py" in e for e in errs)
    assert any("Feature slice missing view.py" in e for e in errs)


def test_arch_guard_detects_unhandled_effect_intent_in_store(tmp_path: Path):
    from scripts.arch_guard import check_all_src_files

    slice_dir = tmp_path / "src" / "ui" / "features" / "broken_intent_slice"
    slice_dir.mkdir(parents=True, exist_ok=True)
    (slice_dir / "state.py").write_text(
        "from dataclasses import dataclass\n\n@dataclass(frozen=True, slots=True)\nclass ExecuteMagicIntent:\n    pass\n",
        encoding="utf-8",
    )
    (slice_dir / "causation.py").write_text("# causation\n", encoding="utf-8")
    (slice_dir / "store.py").write_text(
        "# store forgets to handle ExecuteMagicIntent\n", encoding="utf-8"
    )
    (slice_dir / "view.py").write_text("# view\n", encoding="utf-8")

    errs = check_all_src_files(tmp_path)
    assert any("Unhandled EffectIntent 'ExecuteMagicIntent'" in e for e in errs)
