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
| [dots.tts](https://github.com/studio-dots-ai/dots.tts) | saying a clean word in the actor's voice | Apache 2.0 |
| [transformers](https://github.com/huggingface/transformers) | required by dots.tts | Apache 2.0 |
| [safetensors](https://github.com/huggingface/safetensors) | loading dots.tts's model | Apache 2.0 |
| [Lingua](https://github.com/pemistahl/lingua-py) | required by dots.tts (language detection) | Apache 2.0 |
| [loguru](https://github.com/Delgan/loguru), [pydantic](https://github.com/pydantic/pydantic), [langcodes](https://github.com/georgkrause/langcodes), [torchdiffeq](https://github.com/rtqichen/torchdiffeq) | required by dots.tts | MIT |
| [soundfile](https://github.com/bastibe/python-soundfile) | reading and writing short sound files | BSD 3-Clause |

These in turn use other open source libraries (such as SciPy, scikit-learn and Numba), each under
its own license. dots.tts also asks for WeTextProcessing (a text normaliser that cannot be built on
Windows) and gradio (a web interface); ProfMute uses neither and leaves both out. `speak_stubs\tn`
is a small stand-in so that dots.tts starts without WeTextProcessing; it refuses to run if it is
ever actually used. PyTorch comes from the PyTorch package index rather than PyPI. The exact versions
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

**Speak a clean word** (only when that option is used), into the `speak-models` folder:

- **Gemma 4 12B**, by Google, in Google's own 4-bit build
  ([gemma-4-12B-it-qat-q4_0-gguf](https://huggingface.co/google/gemma-4-12B-it-qat-q4_0-gguf)),
  Apache 2.0. Chooses the clean words.
- **dots.tts.edit**, by dots studio ([Hugging Face](https://huggingface.co/dots-studio/dots.tts.edit)).
  The dots.tts project states that its code and released checkpoints are licensed under Apache 2.0.
  Says the clean words.
- **wav2vec2 large (LV-60k, fine-tuned on LibriSpeech 960h)**, by the wav2vec 2.0 authors, as
  distributed with torchaudio, MIT license. Finds exact word timings.
- **llama.cpp** ([ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp)), build b11312 for
  Windows with CUDA 12.4, including NVIDIA's CUDA runtime libraries, MIT license (the CUDA runtime
  under NVIDIA's license agreement). Runs Gemma on the graphics card.

## Installed separately

**ffmpeg** reads and writes the video files. ProfMute does not include it; it uses the copy
installed on your PC and can install one for you through winget. ffmpeg is licensed under the
LGPL or GPL depending on the build. <https://ffmpeg.org>
