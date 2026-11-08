---
name: release-management
description: |
  Prepare, verify, document, and execute release cycles for PyWarscape Sound. Use when bumping project version, updating release notes, packaging distribution archives, or tagging a release.

  Trigger for:
  - Bumping application or package version
  - Updating CHANGELOG.md, pyproject.toml, scripts/build_dist.py, README.md, or tests/test_disclaimer_dialog.py for a release
  - Executing the mandatory pre-release and post-bump verification gates
  - Packaging standalone desktop distribution archives via scripts/build_dist.py
  - Creating release commits and annotated git tags (e.g. v0.2.0)

  DO NOT trigger for:
  - General feature development or refactoring without release intent
  - Updating test factories or synthetic fixtures (use test-factories skill)
  - Binary SoundBank chunk editing (use bnk-binary skill)
  - UI feature slice development (use feature-slice skill)
---

# Release Management & Distribution Workflow

This skill defines the canonical, deterministic procedure for preparing, validating, and tagging releases of **PyWarscape Sound**.

---

## Architectural Context & Release Strategy

PyWarscape Sound follows [Semantic Versioning (SemVer 2.0.0)](https://semver.org/) (`MAJOR.MINOR.PATCH`):
- **MAJOR**: Incompatible architectural breaks, major data format overhauls.
- **MINOR**: Backward-compatible new features (e.g. music track replacement, capability matrix, new UI panels).
- **PATCH**: Backward-compatible bug fixes, minor UI polish, documentation revisions.

Releases are published as standalone Windows desktop bundles packaged with PyInstaller and bundled with integrity-verified `tools/vgmstream/` binaries. The automated release pipeline is triggered on GitHub Actions whenever an annotated git tag matching `v*.*.*` is pushed.

---

## Canonical Release Files Checklist

Whenever cutting a release to version `v<X.Y.Z>`, the following files **must be updated in lockstep**:

| # | File Path | Key Update Required | Verification / Invariant |
|---|---|---|---|
| 1 | `pyproject.toml` | `version = "<X.Y.Z>"` under `[project]` | Core package metadata. Synchronize with `uv lock` if needed. |
| 2 | `CHANGELOG.md` | Add `## [<X.Y.Z>] - YYYY-MM-DD` section | Follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/): `Added`, `Changed`, `Fixed`, `Removed`, `Security`. |
| 3 | `scripts/build_dist.py` | Update `default="<X.Y.Z>"` in `main()` parser | Standalone builder defaults to current active release. |
| 4 | `README.md` | Update release version examples | Update version strings in build command, archive name, and git commit/tag snippets. |
| 5 | `tests/test_disclaimer_dialog.py` | Add `assert "[<X.Y.Z>]" in content` and `text` | Ensures in-app `ChangelogDialog` and disclaimer can locate current release notes. |

---

## Mandatory Verification Loop (Pre-Release Gates)

Never cut or tag a release without all gates passing cleanly:

```powershell
# 1. Mandatory auto-format check
uv run ruff format --check src scripts tests

# 2. Mandatory linter check
uv run ruff check src scripts tests

# 3. Static type analysis
uv run ty check src

# 4. Architecture boundary and cleanliness enforcement
uv run scripts/arch_guard.py; uv run pytest tests/test_cleanliness.py -q

# 5. Full hermetic test suite (1000+ tests, 0 failures)
uv run pytest tests -m "not assets" -q

# 6. Live game tests (if live game installation is available)
uv run pytest tests/test_live_game.py -m live -q
```

---

## Step-by-Step Release Protocol

### Step 1: Pre-Release Verification
Run all 6 verification gates on a clean working tree. If any gate fails, abort release preparation and resolve the defect first.

### Step 2: Show Diff & Request Approval (Build File Safety)
Per `AGENTS.md`, `pyproject.toml` is a build file. Always present the exact proposed unified diffs for `pyproject.toml`, `CHANGELOG.md`, `scripts/build_dist.py`, `README.md`, and `tests/test_disclaimer_dialog.py` to the user and wait for explicit approval before modifying build files.

### Step 3: Apply Version Bumps
Apply the approved diffs to the 5 canonical release files. If `uv.lock` reflects project version metadata, run `uv lock` to synchronize.

### Step 4: Post-Bump Verification
Re-run the verification gates:
```powershell
uv run ruff format src scripts tests
uv run ruff check --fix src scripts tests
uv run ty check src
uv run scripts/arch_guard.py; uv run pytest tests/test_cleanliness.py -q
uv run pytest tests/test_disclaimer_dialog.py tests/test_build_dist.py -q
uv run pytest tests -m "not assets" -q
```

### Step 5: Verify Standalone Distribution Spec
Verify the distribution spec and packaging builder:
```powershell
uv run pytest tests/test_packaging_spec.py tests/test_build_dist.py -q
```

### Step 6: Atomic Release Commit
Stage the updated files and create a conventional commit:
```powershell
git add pyproject.toml uv.lock CHANGELOG.md scripts/build_dist.py README.md tests/test_disclaimer_dialog.py
git commit -m "chore: prepare v<X.Y.Z> release"
```

### Step 7: Create Annotated Tag
Create an annotated git tag pointing to the release commit:
```powershell
git tag -a v<X.Y.Z> -m "Release v<X.Y.Z>"
```

### Step 8: Push Instructions (Agent Invariant)
**NEVER execute `git push` directly.**
Under project rules (`AGENTS.md`), the agent must never push to remote repositories. Always instruct the user to push the commit and tag:
```powershell
git push origin master
git push origin v<X.Y.Z>
```
Explain that pushing the `v<X.Y.Z>` tag triggers the `.github/workflows/release.yml` GitHub Actions pipeline, which builds `dist/PyWarscapeSound-v<X.Y.Z>-windows-x64.zip`, computes `SHA256SUMS.txt`, and creates the GitHub Release.

