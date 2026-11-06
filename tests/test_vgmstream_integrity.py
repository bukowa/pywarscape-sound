import hashlib
from pathlib import Path

# Pinned SHA-256 manifests for all bundled vgmstream binaries
EXPECTED_VGMSTREAM_HASHES: dict[str, str] = {
    "avcodec-vgmstream-59.dll": "4d6cf54e7b3c26ef06e95bdb515a10d1e1bed3ec1ffd87ec3e5c4fbcd2a883f6",
    "avformat-vgmstream-59.dll": "0dde66ea268cccb67b1aa219c1ce879602b839e561a79a00c8215e2688f1a4b2",
    "avutil-vgmstream-57.dll": "a999856c17cfdce3c22b92b6640a7ada6c4ab4c3c6841a863770b72fa0bc19b4",
    "libatrac9.dll": "fe82f1ae13a798337e03942c35351997c23caadb5eb0c6b7a2dc2a521ed8b02e",
    "libcelt-0061.dll": "542254723d9100f91cbf18e41c4aff80287c22a9859e9e545c413d984df440ad",
    "libcelt-0110.dll": "bfcc51d865bb3b6a2793381bf535f23ec423feb722b46333fa8556ccdcafa61a",
    "libg719_decode.dll": "aad61f205ce1f1b61285f6b37b90a331ec8c6ae2f94f361714dc21a12c236960",
    "libmpg123-0.dll": "db9eb1d91b8eb9f47b0968201dbf6c51a9627e539a78afd9ad5f59c5d18fe4df",
    "libspeex-1.dll": "04dbc85fcec6c54671535bf39937a70f2dd040a81ad670a0b84de6ca17b39bff",
    "libvorbis.dll": "5f330a20b19b3c70dc43eedcc95891e65940fca04a77155c573efcdd4c2ca665",
    "swresample-vgmstream-4.dll": "688a81d31ef98a9a6143e1075b2f4c5b79bdfa51e7a14d50d662a0e916dac739",
    "vgmstream-cli.exe": "0ee2626cd5d470cce5980ab010d36b08f9c97c9480e56bbaceb11475628232ff",
}


def test_vgmstream_binaries_sha256_integrity():
    """
    Cryptographic verification test asserting that all bundled vgmstream binaries
    and runtime DLLs in tools/vgmstream match their pinned SHA-256 digests.
    Prevents silent binary corruption or untracked binary modifications.
    """
    repo_root = Path(__file__).resolve().parents[1]
    tools_dir = repo_root / "tools" / "vgmstream"

    assert tools_dir.is_dir(), f"vgmstream directory missing: {tools_dir}"

    for filename, expected_sha256 in EXPECTED_VGMSTREAM_HASHES.items():
        binary_path = tools_dir / filename
        assert binary_path.is_file(), f"Required vgmstream binary missing: {filename}"

        content = binary_path.read_bytes()
        actual_sha256 = hashlib.sha256(content).hexdigest()
        assert actual_sha256 == expected_sha256, (
            f"SHA-256 mismatch for {filename}!\n"
            f"Expected: {expected_sha256}\n"
            f"Actual:   {actual_sha256}"
        )
