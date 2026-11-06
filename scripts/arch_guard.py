# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""
AST Guardian (scripts/arch_guard.py).
Statically verifies architectural purity rules for src production code and tests.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

BANNED_PURE_IMPORTS = {
    "asyncio",
    "httpx",
    "requests",
    "aiohttp",
    "sqlalchemy",
    "psycopg",
    "redis",
    "boto3",
    "logging",
    "socket",
    "subprocess",
    "shutil",
    "random",
    "pygame",
    "PySide6",
    "PyQt5",
    "PyQt6",
    "sqlite3",
}

BANNED_TEST_IMPORTS = {
    "unittest.mock",
    "mock",
}


def _catches_broad_exception(type_node: ast.expr) -> bool:
    """Returns True if the except type expression catches Exception or BaseException."""
    if isinstance(type_node, ast.Name):
        return type_node.id in ("Exception", "BaseException")
    if isinstance(type_node, ast.Attribute):
        return type_node.attr in ("Exception", "BaseException")
    if isinstance(type_node, ast.Tuple):
        return any(_catches_broad_exception(elt) for elt in type_node.elts)
    return False


def check_file(path: Path, repo_root: Path | None = None) -> list[str]:
    """Inspects a single Python file against architectural invariants."""
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))

    # Normalize relative path for layer identification
    posix_path = path.resolve().as_posix()
    if repo_root is not None:
        try:
            rel_path = path.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            rel_path = posix_path
    else:
        rel_path = posix_path

    # Context classification
    is_in_tests = "/tests/" in f"/{rel_path}/" or rel_path.startswith("tests/")
    is_in_src = ("/src/" in f"/{rel_path}/" or rel_path.startswith("src/")) and not is_in_tests

    is_in_src_bnk = is_in_src and ("/bnk/" in f"/{rel_path}/" or rel_path.startswith("src/bnk/"))
    is_in_src_models = is_in_src and (
        "/models/" in f"/{rel_path}/" or rel_path.startswith("src/models/")
    )
    is_in_src_workspace = is_in_src and (
        "/workspace/" in f"/{rel_path}/" or rel_path.startswith("src/workspace/")
    )
    is_in_src_engine = is_in_src and (
        "/engine/" in f"/{rel_path}/" or rel_path.startswith("src/engine/")
    )
    is_in_src_compiler = is_in_src and (
        "/compiler/" in f"/{rel_path}/" or rel_path.startswith("src/compiler/")
    )
    is_in_src_deps = is_in_src and ("/deps/" in f"/{rel_path}/" or rel_path.startswith("src/deps/"))
    is_in_src_ui = is_in_src and ("/ui/" in f"/{rel_path}/" or rel_path.startswith("src/ui/"))

    stem_lower = path.stem.lower()
    name_lower = path.name.lower()

    is_headless_ui = is_in_src_ui and name_lower in (
        "state.py",
        "structs.py",
        "causation.py",
        "store.py",
        "coordinator.py",
        "overlays.py",
        "columns.py",
    )

    is_pure = is_in_src and (
        name_lower in ("state.py", "structs.py", "ontology.py", "causation.py")
        or stem_lower in ("state", "structs", "ontology", "causation")
    )

    is_state_or_structs = is_in_src and (
        name_lower in ("state.py", "structs.py") or stem_lower in ("state", "structs")
    )

    is_causation = is_in_src and (name_lower == "causation.py" or "causation" in stem_lower)

    is_view_file = is_in_src_ui and (
        name_lower == "view.py"
        or name_lower.endswith(("view.py", "_view.py", "_panel.py", "_dialog.py"))
        or stem_lower.endswith(("_view", "_panel", "_dialog"))
    )

    is_table_or_causation_test = is_in_tests and (
        "test_table" in stem_lower
        or "causation" in stem_lower
        or "test_audio_transport_view" in stem_lower
        or "test_audio_mutation_planner" in stem_lower
    )

    for node in ast.walk(tree):
        # -----------------------------------------------------------------
        # a. Zero Silent Exception Swallowing in src/
        # -----------------------------------------------------------------
        if is_in_src and isinstance(node, ast.ExceptHandler):
            if node.type is None:
                errors.append(f"{path}:{node.lineno}: Bare except forbidden in src")
            elif _catches_broad_exception(node.type):
                if len(node.body) == 1:
                    stmt = node.body[0]
                    if isinstance(stmt, (ast.Pass, ast.Continue)):
                        errors.append(
                            f"{path}:{node.lineno}: Silent exception swallowing forbidden in src "
                            f"(catches broad exception with single {type(stmt).__name__})"
                        )
                    elif isinstance(stmt, ast.Return):
                        if stmt.value is None or (
                            isinstance(stmt.value, ast.Constant) and stmt.value.value is None
                        ):
                            errors.append(
                                f"{path}:{node.lineno}: Silent exception swallowing forbidden in src "
                                f"(catches broad exception with single return None)"
                            )

        # -----------------------------------------------------------------
        # b. Strict Layer Import Matrix
        # -----------------------------------------------------------------
        imported_modules: list[tuple[int, str]] = []
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                full_mod = f"{mod}.{alias.name}" if mod else alias.name
                imported_modules.append((node.lineno, full_mod))

        for lineno, imp in imported_modules:
            # src/bnk/ and src/models/ cannot import src.workspace, src.engine, src.ui, or PySide/PyQt
            if is_in_src_bnk or is_in_src_models:
                if (
                    imp == "src.workspace"
                    or imp.startswith("src.workspace.")
                    or imp == "src.engine"
                    or imp.startswith("src.engine.")
                    or imp == "src.ui"
                    or imp.startswith("src.ui.")
                ):
                    errors.append(
                        f"{path}:{lineno}: Forbidden higher-layer import in bnk/models: {imp}"
                    )
                if imp.startswith(("PySide", "PyQt")):
                    errors.append(f"{path}:{lineno}: Forbidden Qt import in bnk/models: {imp}")

            # src/engine/ cannot import src.workspace (Layer 2 cannot import Layer 3)
            if is_in_src_engine:
                if imp == "src.workspace" or imp.startswith("src.workspace."):
                    errors.append(
                        f"{path}:{lineno}: Forbidden higher-layer import in engine: {imp}"
                    )

            # src/workspace/ cannot import src.engine (decoupled Layer 3 / Layer 2)
            if is_in_src_workspace:
                if imp == "src.engine" or imp.startswith("src.engine."):
                    errors.append(f"{path}:{lineno}: Forbidden engine import in workspace: {imp}")

            # src/workspace/, src/engine/, src/compiler/, and src/deps/ cannot import src.ui or PySide/PyQt
            if is_in_src_workspace or is_in_src_engine or is_in_src_compiler or is_in_src_deps:
                if imp == "src.ui" or imp.startswith("src.ui."):
                    errors.append(
                        f"{path}:{lineno}: Forbidden UI layer import in workspace/engine/compiler/deps: {imp}"
                    )
                if imp.startswith(("PySide", "PyQt")):
                    errors.append(
                        f"{path}:{lineno}: Forbidden Qt import in workspace/engine/compiler/deps: {imp}"
                    )

            # Headless UI files cannot import PySide/PyQt
            if is_headless_ui:
                if imp.startswith(("PySide", "PyQt")):
                    errors.append(
                        f"{path}:{lineno}: Forbidden Qt import in headless UI module: {imp}"
                    )

            # UI Audio Isolation: pygame forbidden in UI outside audio_transport/store.py
            if is_in_src_ui and not rel_path.endswith("src/ui/features/audio_transport/store.py"):
                if imp == "pygame" or imp.startswith("pygame."):
                    errors.append(
                        f"{path}:{lineno}: Forbidden pygame import in UI layer outside audio_transport/store.py: {imp}"
                    )

            # Pure module banned imports
            if is_pure:
                pkg = imp.split(".")[0]
                if pkg in BANNED_PURE_IMPORTS or imp.startswith(("PySide", "PyQt")):
                    errors.append(f"{path}:{lineno}: Banned pure import: {imp}")

            # Table / Causation test mock ban
            if is_table_or_causation_test:
                if imp in BANNED_TEST_IMPORTS or imp.startswith("unittest.mock") or imp == "mock":
                    errors.append(
                        f"{path}:{lineno}: Mocking forbidden in table/causation tests: {imp}"
                    )

        # -----------------------------------------------------------------
        # c. Pure Module Rules: No async def & No mutable dataclass default_factory
        # -----------------------------------------------------------------
        if is_pure and isinstance(node, ast.AsyncFunctionDef):
            errors.append(f"{path}:{node.lineno}: Pure module cannot contain async def")

        if is_state_or_structs and isinstance(node, ast.Call):
            is_field_call = (isinstance(node.func, ast.Name) and node.func.id == "field") or (
                isinstance(node.func, ast.Attribute) and node.func.attr == "field"
            )
            if is_field_call:
                for kw in node.keywords:
                    if kw.arg == "default_factory":
                        if isinstance(kw.value, ast.Name) and kw.value.id in (
                            "list",
                            "dict",
                            "set",
                        ):
                            errors.append(
                                f"{path}:{node.lineno}: Disallowed default_factory={kw.value.id} in @dataclass field; "
                                f"use immutable tuple or frozen structure instead"
                            )

        # -----------------------------------------------------------------
        # d. Causation Rules: No ast.Raise
        # -----------------------------------------------------------------
        if is_causation and isinstance(node, ast.Raise):
            errors.append(f"{path}:{node.lineno}: Causation cannot raise domain exceptions")

        # -----------------------------------------------------------------
        # e. View Encapsulation Rule: No private store attribute access
        # -----------------------------------------------------------------
        if is_view_file and isinstance(node, ast.Attribute):
            if node.attr.startswith("_") and not (
                node.attr.startswith("__") and node.attr.endswith("__")
            ):
                val = node.value
                is_store_ref = False
                if (isinstance(val, ast.Name) and "store" in val.id.lower()) or (
                    isinstance(val, ast.Attribute) and "store" in val.attr.lower()
                ):
                    is_store_ref = True

                if is_store_ref:
                    errors.append(
                        f"{path}:{node.lineno}: View encapsulation violation: "
                        f"forbidden private store attribute access '{node.attr}'"
                    )

        # -----------------------------------------------------------------
        # f. No Cross-Module Private Imports in src/
        # -----------------------------------------------------------------
        if is_in_src and isinstance(node, ast.ImportFrom):
            is_src_import = (
                node.module and (node.module == "src" or node.module.startswith("src."))
            ) or node.level > 0
            if is_src_import:
                for alias in node.names:
                    if alias.name.startswith("_") and not (
                        alias.name.startswith("__") and alias.name.endswith("__")
                    ):
                        errors.append(
                            f"{path}:{node.lineno}: Cross-module private import forbidden in src: "
                            f"'{alias.name}' from '{node.module or '.' * node.level}'"
                        )

        # -----------------------------------------------------------------
        # g. No PYTEST_CURRENT_TEST in src/ Production Code
        # -----------------------------------------------------------------
        if is_in_src:
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "PYTEST_CURRENT_TEST" in node.value:
                    errors.append(
                        f"{path}:{node.lineno}: Reference to 'PYTEST_CURRENT_TEST' forbidden in src"
                    )
            elif isinstance(node, ast.Name) and "PYTEST_CURRENT_TEST" in node.id:
                errors.append(
                    f"{path}:{node.lineno}: Reference to 'PYTEST_CURRENT_TEST' forbidden in src"
                )

        # -----------------------------------------------------------------
        # h. No qapp Fixture Duplication in tests/
        # -----------------------------------------------------------------
        if is_in_tests and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "qapp" and not rel_path.endswith("tests/conftest.py"):
                errors.append(
                    f"{path}:{node.lineno}: Duplicate qapp fixture forbidden in tests "
                    f"(must live only in tests/conftest.py)"
                )

    return errors


def check_all_src_files(repo_root: Path) -> list[str]:
    """Scans all Python files across src/ and tests/ against architectural rules."""
    src_dir = repo_root / "src"
    tests_dir = repo_root / "tests"

    candidate_paths: list[Path] = []
    if src_dir.is_dir():
        candidate_paths.extend(src_dir.rglob("*.py"))
    if tests_dir.is_dir():
        candidate_paths.extend(tests_dir.rglob("*.py"))

    sorted_paths = sorted(candidate_paths, key=lambda p: str(p).lower())

    all_errors: list[str] = []
    for p in sorted_paths:
        if p.is_file() and p.suffix == ".py":
            all_errors.extend(check_file(p, repo_root=repo_root))

    # Module SPEC.md check for src domain packages and src/ui/shell
    if src_dir.is_dir():
        for pkg_dir in sorted(src_dir.iterdir(), key=lambda d: d.name.lower()):
            if not pkg_dir.is_dir() or pkg_dir.name.startswith((".", "__")):
                continue
            if any(pkg_dir.glob("*.py")) and not (pkg_dir / "SPEC.md").is_file():
                all_errors.append(
                    f"{pkg_dir.relative_to(repo_root)}: Module directory missing SPEC.md"
                )

    shell_dir = repo_root / "src" / "ui" / "shell"
    if shell_dir.is_dir() and any(shell_dir.glob("*.py")) and not (shell_dir / "SPEC.md").is_file():
        all_errors.append(f"{shell_dir.relative_to(repo_root)}: Module directory missing SPEC.md")

    # Feature slice completeness check
    features_dir = repo_root / "src" / "ui" / "features"
    if features_dir.is_dir():
        for feature_dir in sorted(features_dir.iterdir(), key=lambda d: d.name.lower()):
            if not feature_dir.is_dir() or feature_dir.name.startswith((".", "__")):
                continue
            if not (feature_dir / "SPEC.md").is_file():
                all_errors.append(
                    f"{feature_dir.relative_to(repo_root)}: Feature slice missing SPEC.md"
                )
            if not (feature_dir / "causation.py").is_file():
                all_errors.append(
                    f"{feature_dir.relative_to(repo_root)}: Feature slice missing causation.py"
                )
            if not (feature_dir / "store.py").is_file():
                all_errors.append(
                    f"{feature_dir.relative_to(repo_root)}: Feature slice missing store.py"
                )
            if not (feature_dir / "view.py").is_file():
                all_errors.append(
                    f"{feature_dir.relative_to(repo_root)}: Feature slice missing view.py"
                )
            if not ((feature_dir / "state.py").is_file() or (feature_dir / "structs.py").is_file()):
                all_errors.append(
                    f"{feature_dir.relative_to(repo_root)}: Feature slice missing state.py or structs.py"
                )

            # Feature slice Intent handling check: every non-NoOp *Intent class defined in
            # state.py, structs.py, or causation.py must be referenced in store.py
            if (feature_dir / "store.py").is_file():
                store_tree = ast.parse(
                    (feature_dir / "store.py").read_text(encoding="utf-8"),
                    filename=str(feature_dir / "store.py"),
                )
                store_names = {n.id for n in ast.walk(store_tree) if isinstance(n, ast.Name)} | {
                    n.attr for n in ast.walk(store_tree) if isinstance(n, ast.Attribute)
                }
                for src_name in ("state.py", "structs.py", "causation.py"):
                    src_file = feature_dir / src_name
                    if not src_file.is_file():
                        continue
                    src_tree = ast.parse(
                        src_file.read_text(encoding="utf-8"),
                        filename=str(src_file),
                    )
                    for node in src_tree.body:
                        if (
                            isinstance(node, ast.ClassDef)
                            and node.name.endswith("Intent")
                            and not node.name.startswith("NoOp")
                        ):
                            if node.name not in store_names:
                                all_errors.append(
                                    f"{feature_dir.relative_to(repo_root)}/store.py: "
                                    f"Unhandled EffectIntent '{node.name}' defined in {src_name}"
                                )

    return all_errors


def main() -> int:
    files = sys.argv[1:]
    repo_root = Path(__file__).resolve().parents[1]

    if not files:
        all_errors = check_all_src_files(repo_root)
    else:
        paths = [Path(f) for f in files]
        all_errors = []
        for p in paths:
            if p.is_file() and p.suffix == ".py":
                all_errors.extend(check_file(p, repo_root=repo_root))

    if all_errors:
        for err in all_errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1

    print("arch_guard: ALL CHECKS PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
