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
| [PyTorch](https://pytorch.org) (with its bundled NVIDIA CUDA libraries) | running the voice model | BSD 3-Clause; NVIDIA license agreements |
| [torchaudio](https://github.com/pytorch/audio) | resampling for the voice model | BSD 2-Clause |
| [librosa](https://librosa.org) | voice model frequency bands | ISC |
| [einops](https://github.com/arogozhnikov/einops) | required by the voice model | MIT |
| [rotary-embedding-torch](https://github.com/lucidrains/rotary-embedding-torch) | required by the voice model | MIT |
| [beartype](https://github.com/beartype/beartype) | required by the voice model | MIT |
| [PyYAML](https://pyyaml.org) | reading voice model settings | MIT |

These in turn use other open source libraries (such as SciPy, scikit-learn and Numba), each under
its own license. PyTorch comes from the PyTorch package index rather than PyPI. The exact versions
are pinned in `uv.lock`.

## Included in ProfMute's source

The voice model code in `voice_separation` (`attend.py`, `bs_roformer.py`,
`mel_band_roformer.py`) is copied from
[Music-Source-Separation-Training](https://github.com/ZFTurbo/Music-Source-Separation-Training)
by Roman Solovyev (ZFTurbo), which builds on Phil Wang's
[BS-RoFormer](https://github.com/lucidrains/BS-RoFormer). MIT license; the text is in
`voice_separation\LICENSE`.

## Downloaded when you first use a model

**Whisper** speech recognition models, by OpenAI, released under the MIT license, in versions
converted for faster-whisper and hosted on [Hugging Face](https://huggingface.co). The distilled
models (`distil-...`) are by the Distil-Whisper project, also MIT licensed.

**Voice models**, listed in `voice-models.txt`:

- **Kim MelBand RoFormer** (the default), vocal model by Kimberley Jensen, from
  [Hugging Face](https://huggingface.co/KimberleyJSN/melbandroformer), MIT license.
- **viperx BS RoFormer**, vocal model by viperx, downloaded from the
  [Ultimate Vocal Remover](https://github.com/TRvlvr/model_repo) model repository. Its author has not
  published license terms for it.

## Installed separately

**ffmpeg** reads and writes the video files. ProfMute does not include it; it uses the copy
installed on your PC and can install one for you through winget. ffmpeg is licensed under the
LGPL or GPL depending on the build. <https://ffmpeg.org>
