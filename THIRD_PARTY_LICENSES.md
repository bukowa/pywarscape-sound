# Third-Party Licenses & Open-Source Attributions

This document contains licensing information and third-party attributions for **PyWarscape Sound** and its bundled or external dependencies.

---

## 1. Project License: PyWarscape Sound

**PyWarscape Sound** is open-source software licensed under the **MIT License**.

```
MIT License

Copyright (c) 2026 PyWarscape Sound Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 2. Open-Source Compliance & Distribution Architecture

Audio Editor adheres to strict open-source licensing principles:

1. **Dynamic Linking (LGPL Compatibility)**:
   - Libraries licensed under LGPL v2.1 or LGPL v3 (such as PyAV / FFmpeg, PySide6 / Qt, and Pygame) are consumed exclusively as dynamic links or shared binary extensions installed via standard package managers (`pip` / `uv`).
   - The user or downstream developer retains the freedom to modify, relink, or substitute these shared libraries with different versions without modifying Audio Editor's source code.

2. **External Process Execution (Subprocess Isolation)**:
   - Standalone CLI utilities (such as `vgmstream-cli`) are executed out-of-process via standard operating system process pipes (`subprocess.run`). Audio Editor communicates with these tools exclusively across standard process boundaries (command line flags and piped stdout), preserving strict separation between independent programs.

3. **Permissive Codebase**:
   - Audio Editor's own source code remains fully under the permissive MIT license and contains no modified copyleft source code.

---

## 3. Third-Party Components & Attributions

### PyAV (and FFmpeg)
- **Component**: `PyAV` (Python bindings for FFmpeg)
- **License**: GNU Lesser General Public License (LGPL) version 2.1 or later (PyAV codebase: BSD 2-Clause; FFmpeg binaries: LGPL v2.1+)
- **Upstream URLs**:
  - PyAV: [https://github.com/PyAV-Org/PyAV](https://github.com/PyAV-Org/PyAV)
  - FFmpeg: [https://ffmpeg.org](https://ffmpeg.org)
- **Description**: Audio decoding, remuxing, resample conversions (32 kHz Vorbis), and stream container inspection.
- **Compliance**: PyAV links dynamically with FFmpeg shared libraries (`avcodec`, `avformat`, `avutil`, `swresample`, `swscale`). Users may replace the underlying FFmpeg shared libraries in their virtual environment without altering Audio Editor.

### vgmstream
- **Component**: `vgmstream` (standalone CLI decoder `vgmstream-cli`)
- **License**: ISC License (with third-party codecs under BSD / MIT / LGPL)
- **Upstream URL**: [https://github.com/vgmstream/vgmstream](https://github.com/vgmstream/vgmstream)
- **Description**: High-fidelity decoding of proprietary video game audio formats, specifically Wwise `.wem` containers (ADPCM and Vorbis).
- **Compliance**: Executed exclusively as an external process binary. Audio Editor does not link against vgmstream internal structures.
- **ISC License Text**:
  ```
  Permission to use, copy, modify, and/or distribute this software for any
  purpose with or without fee is hereby granted, provided that the above
  copyright notice and this permission notice appear in all copies.

  THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
  WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
  MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
  ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
  WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
  ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
  OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
  ```

### PySide6 (Qt for Python)
- **Component**: `PySide6`
- **License**: GNU Lesser General Public License (LGPL) version 3 / GNU General Public License (GPL) version 3 / Commercial
- **Upstream URL**: [https://wiki.qt.io/Qt_for_Python](https://wiki.qt.io/Qt_for_Python) / [https://www.qt.io](https://www.qt.io)
- **Description**: Official Python bindings for the Qt application framework, powering the desktop graphical user interface.
- **Compliance**: PySide6 and Qt libraries are loaded dynamically as shared objects (`.dll` / `.so`). Audio Editor does not modify Qt or PySide6 source code.

### RPFM (Rusted PackFile Manager)
- **Component**: `rpfm`
- **License**: MIT License
- **Upstream URL**: [https://github.com/Frodo45127/rpfm](https://github.com/Frodo45127/rpfm)
- **Description**: Total War PFH4 / PFH5 packfile binary structure layouts, schemas, and manifest specifications (implemented via pure Python in Audio Editor without external binaries).
- **License Notice**:
  ```
  Copyright (c) 2018-2026 Frodo45127

  Permission is hereby granted, free of charge, to any person obtaining a copy
  of this software and associated documentation files (the "Software"), to deal
  in the Software without restriction, including without limitation the rights
  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
  copies of the Software, and to permit persons to whom the Software is
  furnished to do so, subject to the following conditions:

  The above copyright notice and this permission notice shall be included in all
  copies or substantial portions of the Software.

  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
  SOFTWARE.
  ```

### Pygame / pygame-ce
- **Component**: `pygame` / `pygame-ce`
- **License**: GNU Lesser General Public License (LGPL) version 2.1
- **Upstream URLs**:
  - pygame-ce: [https://github.com/pygame-community/pygame-ce](https://github.com/pygame-community/pygame-ce)
  - pygame: [https://github.com/pygame/pygame](https://github.com/pygame/pygame)
- **Description**: Cross-platform low-latency real-time audio playback backend.
- **Compliance**: Pygame dynamically binds to SDL2 audio libraries. Audio Editor interacts strictly through the public Python module interface.

---

## 4. LGPL Compliance Notice & User Rights

For all dependencies licensed under LGPL (including FFmpeg / PyAV, Qt / PySide6, and Pygame):

1. **Source Code Availability**:
   - The upstream source code for these libraries is publicly available at the URLs listed above.
   - You may obtain, modify, and recompile the source code of any of the LGPL dependencies.

2. **Relinking and Replacement**:
   - Under LGPL v2.1 (Section 6) and LGPL v3 (Section 4), users are permitted to replace the LGPL components with customized or recompiled versions. Because these dependencies are distributed as dynamically linked Python C extensions and shared libraries (`.dll` on Windows), users may replace the `.whl` or compiled shared library binaries inside their Python environment without recompiling Audio Editor.
