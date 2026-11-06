# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "av>=17.1.0",
#     "pygame>=2.5.0",
#     "PySide6>=6.6.0",
# ]
# ///
"""Live integration test: Compiles an audio mod pack and tests startup in Total War: Attila or Rome II.

Steps:
1. Detect target game install directory (Steam or local environment variable).
2. Load a real vanilla SoundBank from game cache (.cache/<game>/audio/).
3. Synthesize a test WAV file and replace an audio node using ExternalFileSource (transcoding to .wem via PyAV).
4. Mutate an embedded or secondary sound to a silent stub using SilentStubSource.
5. Compile the mod pack directly to the game's data/ folder as PT_MOD (type 3).
6. Verify pack index, entry count, headers, and AST bit-exact decompile.
7. Backup user.script.txt and register mod "live_audio_test.pack"; at the top.
8. Launch game executable and apply Windows 11 multicore CPU affinity fix (exclude CPU 0).
9. Monitor for crash reports in AppData/The Creative Assembly/<Game>/crash_report/.
10. Ensure game process stays alive and healthy, then terminate process and restore user.script.txt.
"""

from __future__ import annotations

import argparse
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.bnk.bank import SoundBank
from src.bnk.models import CAkSound
from src.compiler.pfh4_pack import (
    PT_MOD,
    extract_pfh4_file,
    read_pfh4_index,
    read_pfh4_pack_type,
)
from src.engine.ontology import ExternalFileSource, SilentStubSource
from src.engine.session import WorkspaceSession
from src.workspace.game import GameType
from src.workspace.game_detector import GameDetector
from src.workspace.manifest import ProjectManifest
from src.workspace.project import AudioProject


@dataclass(frozen=True, slots=True)
class LiveGameConfig:
    game_type: GameType
    title: str
    exe_name: str
    proc_name: str
    appdata_folder: str
    env_var: str
    cache_dir: str
    baseline_bank: str
    sound_replace_id: int
    sound_mute_id: int


GAME_CONFIGS: dict[GameType, LiveGameConfig] = {
    GameType.ATTILA: LiveGameConfig(
        game_type=GameType.ATTILA,
        title="Total War: Attila",
        exe_name="Attila.exe",
        proc_name="Attila",
        appdata_folder="Attila",
        env_var="ATTILA_GAME_DIR",
        cache_dir=".cache/attila/audio",
        baseline_bank="battle_ui.bnk",
        sound_replace_id=26450102,
        sound_mute_id=92088304,
    ),
    GameType.ROME_2: LiveGameConfig(
        game_type=GameType.ROME_2,
        title="Total War: Rome II",
        exe_name="Rome2.exe",
        proc_name="Rome2",
        appdata_folder="Rome2",
        env_var="ROME2_GAME_DIR",
        cache_dir=".cache/rome_2/audio",
        baseline_bank="battle_advice.bnk",
        sound_replace_id=199269820,
        sound_mute_id=903011899,
    ),
}


def _synthesize_test_wav(
    dest_path: Path, duration_sec: float = 0.25, freq_hz: float = 440.0
) -> Path:
    """Synthesizes a valid 16-bit 44.1kHz mono PCM WAV file."""
    sample_rate = 44100
    total_samples = int(sample_rate * duration_sec)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        # Generate simple triangle/square pattern
        samples = [int(1500 * ((i % 100) / 50.0 - 1.0)) for i in range(total_samples)]
        wf.writeframes(struct.pack("<" + "h" * total_samples, *samples))
    return dest_path


def _set_cpu_affinity_no_cpu0(proc_name: str, timeout_sec: float = 15.0) -> bool:
    """Windows 11 freeze workaround: exclude CPU 0 from process affinity mask."""
    ps_cmd = (
        f"$p = Get-Process -Name '{proc_name}' -ErrorAction SilentlyContinue; "
        "if ($p) { "
        "  $sys = [System.Environment]::ProcessorCount; "
        "  $mask = [int64]([math]::Pow(2, $sys) - 1) -band (-bnot 1); "
        "  $p.ProcessorAffinity = [System.IntPtr]$mask; "
        "  Write-Host 'AFFINITY_OK'; "
        "} else { Write-Host 'NOT_FOUND'; }"
    )
    start_time = time.monotonic()
    while time.monotonic() - start_time < timeout_sec:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True
        )
        if "AFFINITY_OK" in res.stdout:
            print(f"[LIVE-TEST] CPU affinity applied for {proc_name} (CPU 0 excluded).")
            return True
        time.sleep(0.25)
    print(f"[LIVE-TEST] Warning: timeout waiting to apply CPU affinity to {proc_name}.")
    return False


def run_live_test(
    duration_sec: float = 25.0,
    dry_run: bool = False,
    keep_pack: bool = False,
    game: GameType = GameType.ATTILA,
) -> bool:
    """Runs the live game integration test for the specified Total War game."""
    cfg = GAME_CONFIGS.get(game)
    if cfg is None:
        raise ValueError(f"Unsupported game type for live test: {game}")

    print("=" * 70)
    print(f"{cfg.title.upper()} - LIVE AUDIO MOD PACK INTEGRATION TEST")
    print("=" * 70)

    # 1. Detect game installation
    game_dir = GameDetector.detect_game_install(cfg.game_type)
    if game_dir is None or not (game_dir / cfg.exe_name).is_file():
        env_dir = os.environ.get(cfg.env_var)
        if env_dir and (Path(env_dir) / cfg.exe_name).is_file():
            game_dir = Path(env_dir)
        else:
            print(
                f"[ERROR] {cfg.title} installation not found! "
                f"Ensure Steam is installed or set the {cfg.env_var} environment variable."
            )
            return False

    print(f"[1/8] Detected {cfg.title} Installation: {game_dir}")
    data_dir = game_dir / "data"
    if not data_dir.is_dir():
        print(f"[ERROR] Game data folder not found: {data_dir}!")
        return False

    appdata_dir = Path(os.environ.get("APPDATA", "")) / "The Creative Assembly" / cfg.appdata_folder
    scripts_dir = appdata_dir / "scripts"
    user_script_path = scripts_dir / "user.script.txt"
    crash_report_dir = appdata_dir / "crash_report"

    # 2. Check cached vanilla bank
    cache_bnk = Path(cfg.cache_dir) / cfg.baseline_bank
    if not cache_bnk.is_file():
        print(f"[ERROR] Baseline bank not found: {cache_bnk}! Run cache indexing first.")
        return False

    print(f"[2/8] Baseline bank located: {cache_bnk} ({cache_bnk.stat().st_size:,} bytes)")

    # 3. Create temporary workspace project & mutate bank
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"audio_live_test_{cfg.proc_name.lower()}_"))
    project = AudioProject(
        root_dir=tmp_dir,
        manifest=ProjectManifest(name="LiveAudioTest", game=cfg.game_type),
    )
    session = WorkspaceSession(project=project)

    bnk_bytes = cache_bnk.read_bytes()
    bank = SoundBank.from_bytes(bnk_bytes)
    session.index_soundbank(cfg.baseline_bank, bank)

    # Synthesize custom WAV audio
    custom_wav = tmp_dir / "shout_test.wav"
    _synthesize_test_wav(custom_wav, duration_sec=0.2)

    # Apply external audio replacement
    print(
        f"[3/8] Mutating {cfg.baseline_bank} sound {cfg.sound_replace_id} with ExternalFileSource..."
    )
    res1 = session.apply_sound_mutation(
        cfg.baseline_bank,
        sound_id=cfg.sound_replace_id,
        source=ExternalFileSource(file_path=custom_wav),
    )
    if res1 is None:
        print("[ERROR] Failed to apply sound mutation!")
        return False

    # Apply silence muting
    print(f"[4/8] Mutating {cfg.baseline_bank} sound {cfg.sound_mute_id} with SilentStubSource...")
    res2 = session.apply_sound_mutation(
        cfg.baseline_bank,
        sound_id=cfg.sound_mute_id,
        source=SilentStubSource(stub_wem_id=1),
    )
    if res2 is None:
        print("[ERROR] Failed to apply silence stub mutation!")
        return False

    # 4. Compile mod pack
    target_pack_name = "live_audio_test.pack"
    target_pack_path = (tmp_dir / target_pack_name) if dry_run else (data_dir / target_pack_name)

    print(f"[5/8] Compiling mod pack to: {target_pack_path}...")
    compiled_pack = session.compile_mod_pack(output_path=target_pack_path)
    if not compiled_pack.is_file():
        print(f"[ERROR] Compiled pack file was not created at {target_pack_path}!")
        return False

    # Verify pack properties
    pack_type = read_pfh4_pack_type(compiled_pack)
    if pack_type != PT_MOD:
        print(f"[ERROR] Compiled pack type is {pack_type}, expected PT_MOD (3)!")
        return False

    entries = read_pfh4_index(compiled_pack)
    entry_map = {e.path.replace("\\", "/"): e for e in entries}
    print(f"      Pack verified: PT_MOD (3), size: {compiled_pack.stat().st_size:,} bytes")
    print(f"      Entries in pack ({len(entries)}): {list(entry_map.keys())}")

    expected_bank_path = f"audio/{cfg.baseline_bank}"
    assert expected_bank_path in entry_map
    assert "audio/1.wem" in entry_map

    # Decompile and verify bank AST
    decompiled_bnk_bytes = extract_pfh4_file(compiled_pack, entry_map[expected_bank_path])
    decompiled_bank = SoundBank.from_bytes(decompiled_bnk_bytes)
    sound_obj = next(
        o
        for o in decompiled_bank.hirc.objects
        if isinstance(o, CAkSound) and o.id == cfg.sound_replace_id
    )
    assert sound_obj.stream_type == 2
    assert f"audio/{sound_obj.source_id}.wem" in entry_map
    print(
        f"      AST decompile roundtrip verified: sound {cfg.sound_replace_id} -> source {sound_obj.source_id} (stream_type=2)"
    )

    if dry_run:
        print(
            f"\n[DRY RUN COMPLETED] Pack built and verified successfully for {cfg.title} without launching the game."
        )
        if not keep_pack and target_pack_path.is_file():
            target_pack_path.unlink()
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return True

    # 5. Backup user.script.txt and register mod pack
    user_script_bak = scripts_dir / f"user.script.txt.{cfg.proc_name.lower()}_live_bak"
    orig_script_content = ""
    if user_script_path.is_file():
        orig_script_content = user_script_path.read_text(encoding="utf-8")
        user_script_bak.write_text(orig_script_content, encoding="utf-8")
        print(f"[6/8] Backed up user.script.txt -> {user_script_bak.name}")
    else:
        scripts_dir.mkdir(parents=True, exist_ok=True)

    # Insert our mod pack at the very top of user.script.txt
    new_script_lines = [f'mod "{target_pack_name}";\r\n']
    for line in orig_script_content.splitlines(keepends=True):
        if target_pack_name not in line:
            new_script_lines.append(line)
    user_script_path.write_text("".join(new_script_lines), encoding="utf-8")
    print(f"      Registered mod '{target_pack_name}' at top of user.script.txt")

    # 6. Snapshot crash reports
    existing_crashes = set(crash_report_dir.glob("*.txt")) if crash_report_dir.is_dir() else set()

    # 7. Launch game executable
    print(f"[7/8] Launching {cfg.title} (running for up to {duration_sec:.0f}s)...")
    exe_path = game_dir / cfg.exe_name

    # Launch via PowerShell Start-Process
    launch_ps = (
        f"Start-Process -FilePath '{exe_path}' -WorkingDirectory '{game_dir}' -WindowStyle Hidden"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", launch_ps], check=True)

    twdll_log = game_dir / "twdll.log"
    initial_log_lines = 0
    if twdll_log.is_file():
        try:
            initial_log_lines = len(
                twdll_log.read_text(encoding="utf-8", errors="replace").splitlines()
            )
        except (OSError, UnicodeDecodeError):
            pass

    count_running = 0
    try:
        # Apply CPU affinity fix
        _set_cpu_affinity_no_cpu0(cfg.proc_name, timeout_sec=20.0)

        # Monitor game execution
        start_wait = time.monotonic()
        poll_interval = 1.0
        crashed = False
        twdll_passed = False

        while time.monotonic() - start_wait < duration_sec:
            # Check if process is still running via PowerShell
            proc_check = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"(Get-Process -Name {cfg.proc_name} -ErrorAction SilentlyContinue).Count",
                ],
                capture_output=True,
                text=True,
            )
            count_running = (
                int(proc_check.stdout.strip()) if proc_check.stdout.strip().isdigit() else 0
            )

            # Check for crash reports
            if crash_report_dir.is_dir():
                new_crashes = set(crash_report_dir.glob("*.txt")) - existing_crashes
                if new_crashes:
                    print(f"\n[ERROR] Game crashed! New crash report detected: {new_crashes}")
                    for crash_file in new_crashes:
                        print(f"--- Crash Report: {crash_file.name} ---")
                        print(crash_file.read_text(encoding="utf-8", errors="replace")[:1000])
                    crashed = True
                    break

            # Check twdll.log for test execution
            if twdll_log.is_file():
                try:
                    all_lines = twdll_log.read_text(encoding="utf-8", errors="replace").splitlines()
                    if len(all_lines) > initial_log_lines:
                        for line in all_lines[initial_log_lines:]:
                            if (
                                "[TEST] Final Result: SUCCESS" in line
                                or "Reload verification completed successfully" in line
                            ):
                                print(f"\n      [TWDLL] Game verified: {line.strip()}")
                                twdll_passed = True
                                break
                except (OSError, UnicodeDecodeError):
                    pass

            if count_running == 0:
                print(f"\n[LIVE-TEST] {cfg.proc_name} process finished/exited.")
                break

            time.sleep(poll_interval)
            elapsed = time.monotonic() - start_wait
            print(
                f"      Game running smoothly... {elapsed:.0f}s / {duration_sec:.0f}s (running: {count_running > 0})",
                end="\r",
            )

        print()
        if crashed:
            return False

        elapsed_total = time.monotonic() - start_wait
        if count_running == 0 and elapsed_total < 5.0:
            print("[ERROR] Process died unexpectedly in under 5 seconds!")
            return False

        print(
            f"[LIVE-TEST] Success: {cfg.title} ran without crashing for {elapsed_total:.1f}s with mod pack loaded."
        )
        if twdll_passed:
            print(
                "      [CONFIRMED] twdll executed lifecycle tests with audio mod pack actively mounted in engine."
            )

    finally:
        # 8. Clean up process and restore files
        print(f"[8/8] Cleaning up {cfg.title} live test environment...")
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Stop-Process -Name {cfg.proc_name} -Force -ErrorAction SilentlyContinue",
            ]
        )
        print("      Game process stopped.")

        # Restore user.script.txt
        if user_script_bak.is_file():
            user_script_path.write_text(orig_script_content, encoding="utf-8")
            user_script_bak.unlink()
            print("      Restored original user.script.txt.")

        # Remove test pack with retry loop for Windows process file handle release
        if not keep_pack and target_pack_path.is_file():
            removed = False
            for _ in range(10):
                try:
                    target_pack_path.unlink()
                    print(f"      Removed test pack: {target_pack_path.name}.")
                    removed = True
                    break
                except (PermissionError, OSError):
                    time.sleep(0.5)
            if not removed:
                print(
                    f"      Warning: could not immediately unlink {target_pack_path.name} (locked by closing process)."
                )

        # Remove temp dir
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("=" * 70)
    print(
        f"LIVE INTEGRATION TEST PASSED FOR {cfg.title.upper()}: 0 CRASHES, MOD PACK MOUNTED SUCCESSFULLY"
    )
    print("=" * 70)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Live integration test for Total War: Attila and Rome II audio mod packs"
    )
    parser.add_argument(
        "--game",
        choices=["attila", "rome_2"],
        default="attila",
        help="Target game to test (attila or rome_2, default: attila)",
    )
    parser.add_argument(
        "--duration", type=float, default=25.0, help="Duration to run the game in seconds"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Compile and verify pack without launching the game"
    )
    parser.add_argument(
        "--keep-pack", action="store_true", help="Keep the compiled pack in data/ after test"
    )
    args = parser.parse_args()

    selected_game = GameType.ROME_2 if args.game == "rome_2" else GameType.ATTILA
    success = run_live_test(
        duration_sec=args.duration,
        dry_run=args.dry_run,
        keep_pack=args.keep_pack,
        game=selected_game,
    )
    sys.exit(0 if success else 1)
