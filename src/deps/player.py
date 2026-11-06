"""
Headless Game Audio Playback Service.

Provides in-memory decoding and playback for Audiokinetic Wwise .wem audio streams,
supporting both loose container files and embedded DATA chunk byte slices.
"""

from __future__ import annotations

import io
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from src.bnk.wem import parse_wem_file, parse_wem_header, repair_extracted_wem_bytes

if TYPE_CHECKING:
    import pygame


def resolve_vgmstream_path() -> Path | None:
    """
    Locates the vgmstream-cli executable across PyInstaller frozen runtime bundles,
    the repository tools directory, or system PATH.
    """
    binary_names = ("vgmstream-cli.exe", "vgmstream-cli")

    # 1. PyInstaller frozen bundle (--onefile: sys._MEIPASS, --onedir: executable directory)
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            meipass_dir = Path(sys._MEIPASS)
            for name in binary_names:
                cand = meipass_dir / "vgmstream" / name
                if cand.is_file():
                    return cand

        exe_parent = Path(sys.executable).parent
        for name in binary_names:
            for sub in ("vgmstream", "tools/vgmstream", ""):
                exe_cand = (exe_parent / sub / name) if sub else (exe_parent / name)
                if exe_cand.is_file():
                    return exe_cand

    # 2. Local repository tools directory
    repo_tools = Path(__file__).resolve().parents[2] / "tools" / "vgmstream"
    for name in binary_names:
        repo_cand = repo_tools / name
        if repo_cand.is_file():
            return repo_cand

    # 3. System PATH
    for name in ("vgmstream-cli", "vgmstream-cli.exe"):
        found = shutil.which(name)
        if found:
            found_path = Path(found)
            if found_path.is_file():
                return found_path

    return None


def _run_vgmstream_decode(input_path: Path) -> bytes:
    """
    Executes vgmstream-cli with stdout piping into memory, suppressing console windows on Windows.
    """
    vgmstream_exe = resolve_vgmstream_path()
    if vgmstream_exe is None or not vgmstream_exe.is_file():
        raise FileNotFoundError("vgmstream-cli executable could not be resolved.")

    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE

    res = subprocess.run(
        [str(vgmstream_exe), "-p", "-i", str(input_path)],
        capture_output=True,
        startupinfo=startupinfo,
    )

    if res.returncode != 0:
        err_msg = res.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"vgmstream-cli failed to decode '{input_path.name}' (exit code {res.returncode}): {err_msg}"
        )

    if not res.stdout:
        err_msg = res.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"vgmstream-cli produced empty output for '{input_path.name}': {err_msg}"
        )

    return res.stdout


def decode_wem_to_wav_bytes(wem_source: str | Path | bytes | bytearray | memoryview) -> bytes:
    """
    Decodes an Audiokinetic Wwise .wem audio stream into a standard RIFF WAVE byte buffer.

    Supports uncompressed PCM pass-through, loose files on disk, and raw byte buffers
    (e.g., embedded SoundBank DATA chunk slices) with ephemeral temporary file handling.
    """
    if isinstance(wem_source, (bytes, bytearray, memoryview)):
        raw_bytes = repair_extracted_wem_bytes(bytes(wem_source))

        # Fast pass-through for uncompressed PCM containers (0x0001, 0xFFFE)
        try:
            header = parse_wem_header(raw_bytes)
            if header.format_tag in (0x0001, 0xFFFE):
                return raw_bytes
        except (ValueError, EOFError, struct.error, OSError):
            pass

        # In-memory slice decoding via ephemeral temporary file
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wem", delete=False) as tmp:
                tmp.write(raw_bytes)
                tmp_path = Path(tmp.name)
            return _run_vgmstream_decode(tmp_path)
        finally:
            if tmp_path is not None:
                try:
                    if tmp_path.exists():
                        os.unlink(tmp_path)
                except OSError:
                    pass

    elif isinstance(wem_source, (str, Path)):
        source_path = Path(wem_source)
        if not source_path.is_file():
            raise FileNotFoundError(f"WEM audio file not found: {source_path}")

        raw_bytes = source_path.read_bytes()
        repaired_bytes = repair_extracted_wem_bytes(raw_bytes)
        if repaired_bytes is not raw_bytes:
            try:
                source_path.write_bytes(repaired_bytes)
            except OSError:
                pass
            return decode_wem_to_wav_bytes(repaired_bytes)

        # Fast pass-through for uncompressed PCM containers
        try:
            header = parse_wem_file(source_path)
            if header.format_tag in (0x0001, 0xFFFE):
                return source_path.read_bytes()
        except (ValueError, EOFError, struct.error, OSError):
            pass

        return _run_vgmstream_decode(source_path)

    else:
        raise TypeError(f"Unsupported audio source type: {type(wem_source).__name__}")


def play_wem_buffer(
    wem_source: str | Path | bytes | bytearray | memoryview,
    volume: float = 1.0,
) -> pygame.mixer.Channel | None:
    """
    Decodes the given WEM source into standard WAV bytes and plays it via pygame.mixer.
    Initializes pygame.mixer if needed.
    """
    import pygame

    wav_bytes = decode_wem_to_wav_bytes(wem_source)

    if pygame.mixer.get_init() is None:
        try:
            pygame.mixer.init()
        except pygame.error:
            return None

    try:
        sound = pygame.mixer.Sound(file=io.BytesIO(wav_bytes))
        clamped_vol = max(0.0, min(1.0, float(volume)))
        sound.set_volume(clamped_vol)
        return sound.play()
    except pygame.error:
        return None


class AudioPreviewSink:
    """
    Headless audio preview sink for ephemeral audio auditioning.

    Encapsulates pygame.mixer sound and channel state, providing safe playback
    and cleanup methods for PCM WAV buffers and raw WEM byte streams.
    """

    def __init__(self) -> None:
        self._active_channel: pygame.mixer.Channel | None = None
        self._active_sound: pygame.mixer.Sound | None = None

    def play_wav_bytes(self, wav_bytes: bytes) -> bool:
        """
        Initializes pygame.mixer if needed, stops any active preview,
        plays the given PCM WAV bytes, and returns True on success.
        """
        self.stop()
        if not wav_bytes:
            return False
        try:
            import pygame

            if pygame.mixer.get_init() is None:
                pygame.mixer.init()

            sound = pygame.mixer.Sound(file=io.BytesIO(wav_bytes))
            channel = sound.play()
            self._active_sound = sound
            self._active_channel = channel
            return True
        except (OSError, RuntimeError, AttributeError, ValueError):
            self._active_sound = None
            self._active_channel = None
            return False

    def play_wem_bytes(self, raw_wem_bytes: bytes) -> bool:
        """
        Decodes raw WEM bytes via decode_wem_to_wav_bytes and plays them.
        Returns True on success, False on failure.
        """
        if not raw_wem_bytes:
            return False
        try:
            wav_bytes = decode_wem_to_wav_bytes(raw_wem_bytes)
            return self.play_wav_bytes(wav_bytes)
        except (OSError, RuntimeError, AttributeError, ValueError, EOFError, struct.error):
            return False

    def stop(self) -> None:
        """Safely halts active channel and sound playback."""
        try:
            if self._active_channel is not None:
                self._active_channel.stop()
        except (OSError, RuntimeError, AttributeError, ValueError):
            pass

        try:
            if self._active_sound is not None:
                self._active_sound.stop()
        except (OSError, RuntimeError, AttributeError, ValueError):
            pass
        finally:
            self._active_channel = None
            self._active_sound = None
