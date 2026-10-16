"""Stand-in for WeTextProcessing's `tn` package, which cannot be built on Windows.

dots.tts imports its text normalisers at start-up but ProfMute never asks it to normalise text; if anything
ever does, this fails loudly instead of quietly doing nothing.
"""
