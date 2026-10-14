"""AI models that split a sound into the voice and everything else (music, effects, ambience).

The model code comes from Music-Source-Separation-Training (MIT license, see LICENSE here); the
separation routine below follows its chunked inference. ProfMute uses it to take only the voice out
of the few seconds around a muted word, so the music and effects keep playing.
"""
import torch
from torch import nn


def build_model(architecture, settings):
    """The untrained network for one of the supported architectures, from the 'model' part of its settings."""
    if architecture == "mel_band_roformer":
        from .mel_band_roformer import MelBandRoformer
        return MelBandRoformer(**settings)
    if architecture == "bs_roformer":
        from .bs_roformer import BSRoformer
        return BSRoformer(**settings)
    raise ValueError(f"unknown voice model architecture: {architecture} (use mel_band_roformer or bs_roformer)")


def separate(model, mix, chunk_size, overlap, use_amp=True):
    """The voice in mix (a channels x samples tensor on the model's device), same shape.

    Long sounds are handled in overlapping chunks that are cross-faded, as in the original code.
    """
    fade = chunk_size // 10
    step = chunk_size // overlap
    border = chunk_size - step
    length = mix.shape[-1]
    if length > 2 * border and border > 0:
        mix = nn.functional.pad(mix, (border, border), mode="reflect")
    window = torch.ones(chunk_size, device=mix.device)
    window[:fade] = torch.linspace(0, 1, fade, device=mix.device)
    window[-fade:] = torch.linspace(1, 0, fade, device=mix.device)
    result = torch.zeros_like(mix)
    counter = torch.zeros(mix.shape[-1], device=mix.device)
    with torch.autocast(device_type=mix.device.type, enabled=use_amp and mix.device.type == "cuda"), torch.inference_mode():
        i = 0
        while i < mix.shape[-1]:
            part = mix[:, i:i + chunk_size]
            n = part.shape[-1]
            part = nn.functional.pad(part, (0, chunk_size - n), mode="reflect" if n > chunk_size // 2 else "constant")
            out = model(part.unsqueeze(0)).float()[0]
            if out.dim() == 3:          # (stems, channels, samples): the voice is the only stem
                out = out[0]
            w = window.clone()
            if i == 0:
                w[:fade] = 1
            if i + step >= mix.shape[-1]:
                w[-fade:] = 1
            result[:, i:i + n] += out[:, :n] * w[:n]
            counter[i:i + n] += w[:n]
            i += step
    voice = result / counter.clamp(min=1e-8)
    if length > 2 * border and border > 0:
        voice = voice[:, border:-border]
    return torch.nan_to_num(voice)
