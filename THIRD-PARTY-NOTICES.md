# Third-party software

ProfMute itself is MIT licensed (see `LICENSE`). It relies on the software below.

## Included in the package

**uv** (`tools\uv.exe`), by Astral Software Inc. Used once, to download Python and the libraries
on first run. Licensed under either the MIT license or the Apache License 2.0; both texts are in
the `licenses` folder. <https://github.com/astral-sh/uv>

## Downloaded to your PC on first run

These are not part of the package. ProfMute's first-time setup downloads them from the Python
Package Index (PyPI), and each comes with its own license.

| Software | Used for | License |
|---|---|---|
| [Python](https://www.python.org) | running ProfMute | PSF License |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | speech recognition | MIT |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | running the speech model | MIT |
| [NumPy](https://numpy.org) | audio arrays | BSD 3-Clause |
| [PyAV](https://github.com/PyAV-Org/PyAV) | required by faster-whisper | BSD 3-Clause |
| [huggingface_hub](https://github.com/huggingface/huggingface_hub) | downloading models | Apache 2.0 |
| [tokenizers](https://github.com/huggingface/tokenizers) | required by faster-whisper | Apache 2.0 |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | required by faster-whisper | MIT |
| NVIDIA cuBLAS, cuDNN and CUDA NVRTC | running on an NVIDIA graphics card | NVIDIA software license agreements |

The exact versions are pinned in `uv.lock`.

## Downloaded when you first use a model

**Whisper** speech recognition models, by OpenAI, released under the MIT license, in versions
converted for faster-whisper and hosted on [Hugging Face](https://huggingface.co). The distilled
models (`distil-...`) are by the Distil-Whisper project, also MIT licensed.

## Installed separately

**ffmpeg** reads and writes the video files. ProfMute does not include it; it uses the copy
installed on your PC and can install one for you through winget. ffmpeg is licensed under the
LGPL or GPL depending on the build. <https://ffmpeg.org>
