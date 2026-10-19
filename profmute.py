"""profmute - mute profanity in a video's main audio track.

Usage:  uv run python profmute.py "C:\\path\\movie.mkv" [--dry] [--srt subs.srt | --no-srt] [--model large-v3]
                                 [--out clean.mkv] [--out-srt clean.srt] [--log-dir folder] [--words words.txt]
                                 [--pad-before 0.02] [--pad-after 0.30] [--device auto|cuda|cpu]
                                 [--confirm] [--conflicts ask|auto] [--unresolved ask|leave]
                                 [--no-fade] [--all-channels] [--no-front-check] [--no-separate] [--voice-model NAME]
Output: <name>.clean.mkv next to the original (or --out), and a log of the muted words,
        <name>.profmute.txt, in a "log" folder next to this program (or --log-dir).
        The original file is never modified.
        When subtitles are available, also <name>.clean.en.srt next to the clean copy (or --out-srt):
        the same subtitles with the profanity deleted.
For a window instead of a command line, run profmute_gui.py (or double-click ProfMute.exe).

The words to mute come from words.txt next to this program (or --words); the models offered in the
window come from models.txt. Both are plain text and meant to be edited.

Subtitles only double-check Whisper, they are never a mute source: a subtitle line with profanity
that Whisper did not hear gets re-listened to, and is listed as UNRESOLVED if it is still not found.
A word Whisper heard that the subtitles do not contain is a conflict: --conflicts ask lets you
decide, --conflicts auto lets three listens decide. --confirm double-checks where every word is.
Subtitle lookup order: --srt, then <name>.en.srt / <name>.srt next to the movie, then an English
text subtitle track inside the file.
"""
import argparse, bisect, gc, hashlib, json, os, re, secrets, shutil, subprocess, sys, tempfile
from collections import Counter
from pathlib import Path

__version__ = "1.5.1"
HERE = Path(__file__).resolve().parent

# --- make the pip-installed CUDA DLLs visible (Windows) ---
site = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
for sub in ("cublas", "cudnn", "cuda_nvrtc"):
    d = site / sub / "bin"
    if d.is_dir():
        os.add_dll_directory(str(d))
        os.environ["PATH"] = str(d) + os.pathsep + os.environ["PATH"]

# ---- The word list people edit is words.txt. This copy is what a fresh words.txt contains, and what
# ---- is used when that file is missing.
DEFAULT_WORDS = r"""# ProfMute word list - edit freely, then run ProfMute again.
# Lines starting with # are notes. Capital letters do not matter.

[words]
# One word per line. A * stands for "any letters":
#   hell      only the word hell (not hello, not shell)
#   bitch*    bitch, bitches, bitching ...
#   *fuck*    any word with fuck in it
*fuck*
*shit*
bitch*
asshole*
cunt*
pussy
pussies
cock
cocks
cocksucker*
dickhead*
whore*
slut*
bastard*
wank*
twat*
jackass*
dumbass*
badass
goddam*
damn*
hell
ass
asses
piss*
dick
dicks
douche*
blowjob*
handjob*
rimjob*
cum
cums
cumming
cummed
cumshot*
jizz*
cuck
cucks
cucked
cucking
cuckold*
tits
titties
titty
boner
boners
dildo*
hardon*
deepthroat*
buttsex

[phrases]
# Several words on a line: muted from the first word to the last, when said together.
blow job*
son of a bitch*
sons of bitches
god damn*
jesus christ
mother fuck*
hand job*
rim job*
jerk off
jerks off
jerked off
jerking off
jack off
jacks off
jacked off
jacking off
deep throat*
butt sex

[censored]
# Advanced. Speech-to-text sometimes writes a swear word bleeped, like f*** or s**t.
# Each line is a regular expression for one such spelling. Leave these alone if unsure.
f\*+\w*
\w*s\*+t\w*
b\*+tch\w*
mother\W*f\w*
\w*f\W?\*{2,}\w*

[cut-off]
# Word beginnings that subtitles cut off, as in "Oh, sh..." or "What the f-".
# These never mute anything by themselves; they only make ProfMute listen to that line again.
f
fu
fuc
sh
shi
bullsh
horsesh
bitc
assh

[replacements]
# Only used with "Speak a clean word": your own choice of clean word, used instead of the AI's choice.
#   swear = clean word       (a * stands for "any letters", as above)
# For example (remove the # to use a line):
#   motherfucker* = son of a gun
#   son of a bitch* = son of a gun
"""

# ---- Likewise for models.txt: the Whisper models the window offers. No download locations or sizes
# ---- here on purpose - faster-whisper knows where each name lives, and sizes are looked up online.
DEFAULT_MODELS = """# ProfMute model list. One model per line:   name | note
# The first line is the default.
# name is a faster-whisper model name (large-v3, small.en ...), or a Hugging Face
# repository (someone/some-model), or a folder on this PC that holds a model.
large-v3 | biggest, most accurate, slowest
large-v2 | the previous big model, same speed
large-v3-turbo | much faster, a little less accurate
distil-large-v3 | much faster, a little less accurate
medium.en | faster, less accurate
small.en | fast, misses more words
base.en | very fast, misses many words
tiny.en | fastest, least accurate
"""

# ---- Likewise for voice-models.txt: the AI models that take the voice out of a muted stretch while the
# ---- music and effects keep playing. Download locations are listed here only as defaults; edit the file.
DEFAULT_VOICE_MODELS = """# ProfMute voice model list: AI models that remove the voice but keep the music and sound effects.
# One model per line:   name | architecture | weights address | settings address
# The first line is the default. A model downloads itself into the "voice-models" folder next to
# ProfMute the first time it is used. architecture is mel_band_roformer or bs_roformer.
Kim MelBand RoFormer | mel_band_roformer | https://huggingface.co/KimberleyJSN/melbandroformer/resolve/main/MelBandRoformer.ckpt | https://raw.githubusercontent.com/ZFTurbo/Music-Source-Separation-Training/5a3e16d1f7e6ac489bddbeb25069595527e170ce/configs/KimberleyJensen/config_vocals_mel_band_roformer_kj.yaml
viperx BS RoFormer | bs_roformer | https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/model_bs_roformer_ep_317_sdr_12.9755.ckpt | https://raw.githubusercontent.com/ZFTurbo/Music-Source-Separation-Training/5a3e16d1f7e6ac489bddbeb25069595527e170ce/configs/viperx/model_bs_roformer_ep_317_sdr_12.9755.yaml
"""
VOICE_DIR = HERE / "voice-models"
CONTEXT = 3.0   # seconds of sound around a muted word that the voice model hears, so it can tell voice from music

MAX_GAP = 1.0  # seconds; phrase words further apart than this are not treated as a phrase

# ---- EDIT HERE: seconds of extra silence around each word (also --pad-before / --pad-after) ----
# Whisper tends to mark a word's start about right and its end too early, so most of the padding goes after.
PAD_BEFORE = 0.02
PAD_AFTER = 0.30
FADE = 0.03   # seconds the sound takes to fade out before a mute and back in after it (--no-fade: none)

SR = 16000           # sample rate Whisper wants
SRT_TOL = 1.5        # seconds; a subtitle hit counts as heard if Whisper has a hit this close to the line
RESCAN_PAD = 2.0     # seconds of audio added on each side of a subtitle line when re-listening
OFFSET_SEARCH = 30.0 # seconds; how far out of sync a subtitle file may be and still get lined up
OFFSET_SEARCH_WIDE = 120.0  # tried when that fails (e.g. Saving Private Ryan's subtitles: 40 s late throughout)
OFFSET_BIN = 0.2
MIN_AGREEMENT = 0.3  # share of subtitle lines that must agree on the sync, else the file is ignored
LISTENS = ((2.0, 2.0), (4.0, 3.0))   # seconds of audio before/after a word for its second and third listen
VOICE_BAND = "highpass=f=100,lowpass=f=4000"   # the filtered copy of the sound used as a last try for a missed word
ASK = "@@PROFMUTE-ASK "              # a line starting with this asks the window to settle a conflict
FFMPEG_HELP = ("ffmpeg was not found. Install it with:   winget install --id Gyan.FFmpeg -e\n"
               "then start ProfMute again. Or put ffmpeg.exe and ffprobe.exe in a folder named ffmpeg next to ProfMute.")
FFMPEG, FFPROBE = "ffmpeg", "ffprobe"   # replaced by full paths in need_ffmpeg()

STRIP = ".,!?;:\"'()[]-…“”‘’♪ "
TAGS = re.compile(r"<[^>]+>|\{[^}]*\}")
PIECE = re.compile(r"(?:<[^>]+>|\{[^}]*\}|\S)+")   # one subtitle word, with any tags stuck to it
SPLIT_TAGS = re.compile(r"^((?:<[^>]+>|\{[^}]*\})*)(.*?)((?:<[^>]+>|\{[^}]*\})*)$", re.S)
TERMINAL = ".?!…"
QUOTES = "\"“”"
TEXT_SUBS = ("subrip", "ass", "ssa", "mov_text", "webvtt", "text")


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        lines = [ln for ln in r.stderr.splitlines() if ln.strip() and not re.match(r"\s*(lib\w+\s+\d|configuration:|built with|ffmpeg version|ffprobe version)", ln)]
        print("\n".join(lines[-3:]))            # the reason; not ffmpeg's version and build details before it
        sys.exit(f"{Path(cmd[0]).stem} failed")
    return r


def read_text(path):
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def find_tool(name):
    """ffmpeg / ffprobe: a copy in an "ffmpeg" folder next to the program wins, then whatever is installed."""
    for folder in (HERE / "ffmpeg", HERE / "ffmpeg" / "bin"):
        if (folder / f"{name}.exe").is_file():
            return str(folder / f"{name}.exe")
    found = shutil.which(name)
    if not found and os.name == "nt":  # installed a moment ago? this process still has the old PATH
        import winreg
        paths = []
        for root, key in ((winreg.HKEY_CURRENT_USER, "Environment"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
            try:
                with winreg.OpenKey(root, key) as k:
                    paths.append(os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]))
            except OSError:
                pass
        found = shutil.which(name, path=os.pathsep.join(paths))
    return found


def need_ffmpeg():
    global FFMPEG, FFPROBE
    FFMPEG, FFPROBE = find_tool("ffmpeg"), find_tool("ffprobe")
    if not FFMPEG or not FFPROBE:
        sys.exit(FFMPEG_HELP)


def load_audio(src, audio_index, filters=""):
    """One audio track of the movie as Whisper wants it: 16 kHz mono samples, on the movie's own clock."""
    import wave
    import numpy as np
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        # first_pts=0 pads the start when the audio track begins late, so times in the WAV are the
        # movie's own clock - the one the subtitles and the mute filter use
        run([FFMPEG, "-y", "-i", str(src), "-map", f"0:a:{audio_index}", "-ac", "1", "-ar", str(SR),
             "-af", (filters + "," if filters else "") + "aresample=async=1:first_pts=0", str(wav)])
        with wave.open(str(wav), "rb") as wf:
            return np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


# ---------------------------------------------------------------- voice models

def load_voice_models():
    """The voice models offered, from voice-models.txt next to the program: [(name, architecture, weights, settings)]"""
    def read(text):
        rows = [[part.strip() for part in line.split("|")] for line in map(str.strip, text.splitlines())
                if line and not line.startswith("#")]
        return [tuple(r) for r in rows if len(r) == 4 and all(r)]
    p = HERE / "voice-models.txt"
    return (read(read_text(p)) if p.is_file() else []) or read(DEFAULT_VOICE_MODELS)


def voice_model_files(name):
    folder = VOICE_DIR / re.sub(r"[^\w.-]+", "_", name)
    return folder / "model.ckpt", folder / "settings.yaml"


def fetch(url, dest, label):
    """Download url to dest, showing progress; nothing is left behind if it fails."""
    import urllib.request
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "ProfMute"})
    with urllib.request.urlopen(request, timeout=60) as r, open(part, "wb") as f:
        total, done, shown = int(r.headers.get("Content-Length") or 0), 0, -1
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if total > 5e6 and done * 100 // total != shown:
                shown = done * 100 // total
                print(f"\r    downloading {label}: {shown:3d}% of {total / 1e9:.1f} GB", end="", flush=True)
    if total > 5e6:
        print()
    os.replace(part, dest)


def download_size(url):
    """How big a download is, without downloading it (None when unknown or offline)."""
    import urllib.request
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "ProfMute", "Range": "bytes=0-0"})
        with urllib.request.urlopen(request, timeout=6) as r:
            whole = (r.headers.get("Content-Range") or "").rpartition("/")[2]
            return int(whole) if whole.isdigit() else int(r.headers.get("Content-Length") or 0) or None
    except Exception:
        return None


def list_voice_models():
    out = []
    for name, _, weights, _ in load_voice_models():
        out.append({"name": name, "downloaded": voice_model_files(name)[0].is_file(), "size": download_size(weights)})
    return out


class VoiceRemover:
    """A voice model, downloaded on first use, that takes the voice out of a sound and keeps the rest."""

    def __init__(self, name):
        import torch, yaml
        entry = next((m for m in load_voice_models() if m[0] == name), None)
        if entry is None:
            raise ValueError(f"no voice model called {name!r} in voice-models.txt")
        _, architecture, weights_url, settings_url = entry
        weights, settings = voice_model_files(name)
        if not settings.is_file():
            fetch(settings_url, settings, f"{name} settings")
        if not weights.is_file():
            fetch(weights_url, weights, name)
        with open(settings, encoding="utf-8") as f:
            cfg = yaml.load(f, Loader=yaml.FullLoader)
        from voice_separation import build_model
        self.model = build_model(architecture, dict(cfg["model"]))
        state = torch.load(weights, map_location="cpu", weights_only=True)
        for key in ("state", "state_dict", "model_state_dict"):
            if isinstance(state, dict) and key in state:
                state = state[key]
        self.model.load_state_dict(state)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device).eval()
        audio, inference = cfg["audio"], cfg.get("inference", {})
        self.rate = int(audio["sample_rate"])
        self.chunk = int(inference.get("chunk_size", audio["chunk_size"]))
        self.overlap = int(inference.get("num_overlap", 2))
        self.amp = bool(cfg.get("training", {}).get("use_amp", True))
        self.name = name

    def voice_free(self, audio, rate):
        """audio = samples x channels (1 or 2) at `rate` -> the same sound with the voice taken out."""
        import numpy as np, torch, torchaudio
        from voice_separation import separate
        mix = torch.from_numpy(np.ascontiguousarray(audio.T, dtype=np.float32)).to(self.device)
        if mix.shape[0] == 1:
            mix = mix.repeat(2, 1)                       # the models are trained on stereo
        mix = torchaudio.functional.resample(mix, rate, self.rate)
        voice = separate(self.model, mix, self.chunk, self.overlap, self.amp)
        free = torchaudio.functional.resample(mix - voice, self.rate, rate)
        free = free[:, :len(audio)]
        if free.shape[1] < len(audio):
            free = torch.nn.functional.pad(free, (0, len(audio) - free.shape[1]))
        if audio.shape[1] == 1:
            free = free.mean(dim=0, keepdim=True)
        return free.T.cpu().numpy()


# ---------------------------------------------------------------- writing the clean audio

LOSSLESS = ("truehd", "mlp", "flac", "alac", "wavpack", "tta") # decoded at 32 bits so nothing is lost
_layouts = None


def channel_names(layout, channels):
    """The channels of an audio track in the order ffmpeg decodes them, e.g. ['FL', 'FR', 'FC', ...], or None."""
    global _layouts
    if "+" in layout:
        names = layout.split("+")
    else:
        if _layouts is None:
            listing = run([FFMPEG, "-hide_banner", "-layouts"]).stdout
            table = listing.split("Standard channel layouts:")[-1].splitlines()
            _layouts = dict(line.split()[:2] for line in table if len(line.split()) >= 2 and line.split()[0] != "NAME")
        names = _layouts.get(layout, "").split("+")
    return names if len(names) == channels and all(names) else None


def first_line(e):
    """An error's message, short enough for a log line."""
    return (str(e).strip().splitlines() or [type(e).__name__])[0][:300]


def mute_samples(data, rate, spans, ramp, fills=None):
    """Take the words out of data (frames x channels), in place.

    spans = [(start, end, channels), ...] in seconds. Inside a span those channels are replaced by
    fills[i] (frames of that span's region x those channels: the same sound with the voice removed),
    or by silence when there is no fill. With ramp > 0 the change fades in over `ramp` samples just
    before each span and back out just after it (raised cosine), so the span itself is fully replaced.
    Nothing else is touched.
    """
    import numpy as np
    frames = len(data)
    top = float(np.iinfo(data.dtype).max)
    down = 0.5 + 0.5 * np.cos(np.pi * np.arange(1, ramp + 1) / ramp) if ramp else None   # just under 1 ... 0
    for i, (s, e, targets) in enumerate(spans):
        a, b = region(s, e, rate, ramp, frames)
        if b <= a:
            continue
        gain = np.zeros(b - a, dtype=np.float64)
        if ramp:
            head = min(ramp, int(round(s * rate)) - a)          # fade samples that fit before the span
            tail = min(ramp, b - int(round(e * rate)))          # fade samples that fit after it
            gain[:head] = down[ramp - head:] if head < ramp else down
            if tail > 0:
                gain[len(gain) - tail:] = down[::-1][:tail]
        block = data[a:b, targets].astype(np.float64) * gain[:, None]
        if fills is not None and fills[i] is not None:
            block += fills[i] * top * (1 - gain[:, None])
        data[a:b, targets] = np.clip(np.round(block), -top - 1, top).astype(data.dtype)


def region(s, e, rate, ramp, frames):
    """The samples a span changes, fades included."""
    return max(0, int(round(s * rate)) - ramp), min(frames, int(round(e * rate)) + ramp)


def track_info(src, audio_index):
    """(all streams, the audio track, its channel names or None) of a movie."""
    streams = json.loads(run([FFPROBE, "-v", "error", "-show_entries",
                              "stream=index,codec_type,codec_name,channels,channel_layout,sample_rate,bits_per_raw_sample:"
                              "stream_disposition", "-of", "json", str(src)]).stdout)["streams"]
    audio = [s for s in streams if s["codec_type"] == "audio"]
    if audio_index >= len(audio):
        sys.exit(f"the movie has no audio track number {audio_index}")
    track = audio[audio_index]
    layout = track.get("channel_layout", "")
    return streams, track, channel_names(layout, int(track["channels"])) if layout else None


FRONT = ("FL", "FR", "FLC", "FRC")   # where some mixes leak dialogue besides the centre
PAIRS = (("FL", "FR"), ("FLC", "FRC"), ("BL", "BR"), ("SL", "SR"), ("TFL", "TFR"), ("TBL", "TBR"))


def plan_channels(names, channels, dialogue_only):
    """Which channels a mute changes.

    -> (channels for every word, extra front channels for the words also heard there, words for the log)
    """
    if dialogue_only and names and "FC" in names and channels > 2:
        front = [names.index(n) for n in FRONT if n in names]
        return [names.index("FC")], front, "only the dialogue (centre) channel"
    return list(range(channels)), [], "all channels"


def groups(targets, names):
    """Split channels into stereo pairs (left/right of one pair of speakers) and single channels, for the voice model."""
    targets, out = list(targets), []
    if names:
        for left, right in PAIRS:
            if left in names and right in names and names.index(left) in targets and names.index(right) in targets:
                out.append([names.index(left), names.index(right)])
                targets = [t for t in targets if t not in out[-1]]
    elif len(targets) == 2:
        return [targets]
    return out + [[t] for t in targets]


def work_folder(parent):
    """A new, uniquely named folder for temporary files in `parent`. Made with the folder's normal permissions:
    tempfile.mkdtemp (Python 3.12.4 and later, on Windows) locks a new folder to its owner, and on a network share
    (a NAS) that can lock you out of it, so nothing can be written into it or deleted."""
    for _ in range(100):
        path = Path(parent) / f".profmute-{secrets.token_hex(4)}"
        try:
            path.mkdir()
            return str(path)
        except FileExistsError:
            continue
    raise OSError(f"could not make a temporary folder in {parent}")


def write_clean_audio(src, out, audio_index, spans, fade, dialogue_only, also_front=(), voice=None, speaking=None):
    """Write the clean copy: every stream of the movie copied as it is, except the cleaned audio track.

    The track is decoded once to a temporary file on the output drive. Only the muted stretches are
    changed, in place; everything else stays sample for sample as decoded.
    dialogue_only: a surround track is changed in its centre (dialogue) channel only, plus its front
    left/right for the spans whose index is in also_front (the word was heard there too).
    voice: a VoiceRemover; the changed channels then keep their music and effects and lose only the voice.
    fade: each change fades in just before its stretch and out just after it.
    speaking: with --speak, {"sentences", "words", "model", "device"} for speak.speak(): the chosen clean
    words are then said in the actor's voice, laid over the muted track.
    -> a sentence for the log saying how it was done
    """
    import numpy as np
    streams, track, names = track_info(src, audio_index)
    channels, rate = int(track["channels"]), int(track["sample_rate"])
    layout = track.get("channel_layout", "")
    wide = track["codec_name"] in LOSSLESS or int(track.get("bits_per_raw_sample") or 0) > 16
    fmt, dtype = ("s32le", np.int32) if wide else ("s16le", np.int16)

    base, front, where = plan_channels(names, channels, dialogue_only)
    plan = [(s, e, base + (front if i in also_front else [])) for i, (s, e) in enumerate(spans)]
    if dialogue_only and base == list(range(channels)):
        where += f" (a {layout or str(channels) + '-channel'} track has no separate dialogue channel)"
    else:
        where += f" of the {layout} track" if base != list(range(channels)) else ""
    if front and also_front:
        where += f", plus front left/right at {len(set(also_front))} spot(s) where the word was heard there too"
    how = f"Muting: {where}" + (f"; the voice removed by {voice.name}, music and effects kept" if voice else ", silenced") + \
          (f", with {FADE * 1000:.0f} ms fades." if fade else ", without fades.")

    duration = float(json.loads(run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "json",
                                     str(src)]).stdout)["format"]["duration"])
    need = duration * rate * channels * np.dtype(dtype).itemsize
    free = shutil.disk_usage(out.parent).free
    if free < need * 1.1 + 200e6:
        sys.exit(f"Not enough free space on the drive of {out.parent}: writing the clean audio needs a temporary "
                 f"file of about {need / 1e9:.1f} GB plus the clean copy itself, and only {free / 1e9:.1f} GB is free.")

    tmp = work_folder(out.parent)
    try:
        raw = os.path.join(tmp, "audio.raw")
        run([FFMPEG, "-y", "-i", str(src), "-map", f"0:a:{audio_index}", "-af", "aresample=async=1:first_pts=0",
             "-f", fmt, "-c:a", "pcm_" + fmt, raw])
        data = np.memmap(raw, dtype=dtype, mode="r+")
        data = data[:data.size - data.size % channels].reshape(-1, channels)
        end = len(data) / rate        # a stretch past the end of the sound (a subtitle line after it): cut short or dropped
        plan = [(s, min(e, end), targets) for s, e, targets in plan if s < end - 0.01]
        ramp, top = int(FADE * rate) if fade else 0, float(np.iinfo(dtype).max)
        fills = None
        if voice:
            fills = []
            for n, (s, e, targets) in enumerate(plan, 1):
                print(f"\r    removing the voice {n}/{len(plan)}", end="", flush=True)
                a, b = region(s, e, rate, ramp, len(data))
                w0, w1 = max(0, a - int(CONTEXT * rate)), min(len(data), b + int(CONTEXT * rate))
                fill = np.zeros((b - a, len(targets)), dtype=np.float64)
                for group in groups(targets, names):
                    sound = data[w0:w1, group].astype(np.float32) / top
                    clean = voice.voice_free(sound, rate)[a - w0:b - w0]
                    for k, c in enumerate(group):
                        fill[:, targets.index(c)] = clean[:, k]
                fills.append(fill)
            print()
        pieces, dialogue = [], None
        if speaking and voice:
            import speak
            dialogue = [names.index("FC")] if names and "FC" in names else list(range(min(2, channels)))
            try:
                pieces = speak.speak(data, rate, top, dialogue, speaking["sentences"], [p[:2] for p in plan], voice,
                                     speaking["model"], speaking["device"], speaking["words"], sys.modules[__name__])
            except Exception as e:   # the clean copy must still be written: those words stay muted
                speaking["trouble"] = f"Speaking the clean words failed ({first_line(e)}); those words were muted instead."
                print("    " + speaking["trouble"])
        mute_samples(data, rate, plan, ramp, fills)
        for first, frames, sound, blend in pieces:     # the spoken words, over the muted track
            now = data[first:first + frames, dialogue].astype(np.float64) / top
            mixed = now * (1 - blend[:, None]) + sound * blend[:, None]
            data[first:first + frames, dialogue] = np.clip(np.round(mixed * top), -top - 1, top).astype(data.dtype)
        data.flush()
        del data

        # every stream of the movie in its own order, the cleaned track taken from the edited file instead
        position = next(i for i, s in enumerate(streams) if s is track)
        cmd = [FFMPEG, "-y", "-i", str(src), "-f", fmt, "-ar", str(rate)]
        cmd += ["-ch_layout", layout] if names else ["-ac", str(channels)]
        cmd += ["-i", raw]
        for i, s in enumerate(streams):
            cmd += ["-map", "1:a:0" if i == position else f"0:{s['index']}"]
        # naming any stream's metadata switches off ffmpeg's automatic copy for all of them, so name each one
        for i, s in enumerate(streams):
            cmd += [f"-map_metadata:s:{i}", f"0:s:{s['index']}"]
        flags = "+".join(k for k, v in (track.get("disposition") or {}).items() if v == 1) or "0"
        cmd += ["-map_metadata", "0", "-map_chapters", "0", "-c", "copy", f"-disposition:a:{audio_index}", flags,
                f"-c:a:{audio_index}", "aac", f"-b:a:{audio_index}", "384k", str(out)]
        run(cmd)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return how


def front_heard(model, src, audio_index, spans, names):
    """Indexes of the spans whose word Whisper also hears in the front left/right speakers (centre left out)."""
    if not names or "FC" not in names or "FL" not in names or "FR" not in names:
        return set()
    sides = load_audio(src, audio_index, "pan=mono|c0=0.5*FL+0.5*FR")
    heard = set()
    for i, (s, e, *_) in enumerate(spans):
        print(f"\r    listening to the front left/right speakers {i + 1}/{len(spans)}", end="", flush=True)
        a = max(0.0, s - 2)
        found = find_hits(transcribe(model, sides[int(a * SR):int((e + 2) * SR)], a))
        if any(overlaps(h, (s, e), 0) for h in found):
            heard.add(i)
    print()
    return heard


def stamp(t):
    t = round(t, 2)
    return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


CONTRACTION = re.compile(r"(he|she|we|they|you|i|it|who|that|there|what)['’](ll|d|s|re|ve|m)")


def norm(word):
    """(raw, tok): lowercased with the outer punctuation stripped, and the letters only. A pronoun's
    contraction keeps its apostrophe ("he'll"), so it is never read as a word on the list ("hell")."""
    raw = word.lower().strip(STRIP)
    if CONTRACTION.fullmatch(raw):
        return raw, raw.replace("’", "'")
    return raw, re.sub(r"[^a-z]", "", raw)


# ---------------------------------------------------------------- word list

class WordListError(ValueError):
    pass


class Rules:
    """A loaded word list. words/censored/cutoff are single regexes, phrases a list of regex lists."""
    def __init__(self, words, phrases, censored, cutoff, source, replacements=()):
        star = lambda entry: "[a-z]*".join(re.escape(part) for part in entry.split("*"))
        either = lambda patterns: re.compile("|".join(f"(?:{p})" for p in patterns) or "(?!)")
        self.words = either(star(w) for w in words)
        self.phrases = [[re.compile(star(w)) for w in phrase] for phrase in phrases]
        self.censored = either(censored)
        self.cutoff = either(re.escape(c) for c in cutoff)
        # [replacements]: (pattern for the swear's words, space-separated letters only, its clean word)
        self.replacements = [(re.compile(" ".join(star(w) for w in pattern)), clean) for pattern, clean in replacements]
        self.source = source
        self.summary = f"{len(words)} words, {len(phrases)} phrases" + \
                       (f", {len(replacements)} replacements" if replacements else "")

    def replacement(self, swear):
        """The word list's own clean word for a swear (its words as heard), or None."""
        tok = " ".join(norm(w)[1] for w in swear.split())
        return next((clean for pattern, clean in self.replacements if pattern.fullmatch(tok)), None)


def parse_words(text, source):
    """Read a word list (see DEFAULT_WORDS for the format). Raises WordListError naming every bad line."""
    sections = {"words": "words", "word": "words", "phrases": "words", "phrase": "words",
                "censored": "censored", "cutoff": "cutoff", "replacements": "replacements", "replacement": "replacements"}
    section, words, phrases, censored, cutoff, replacements, problems = "words", [], [], [], [], [], []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        header = re.fullmatch(r"\[(.+)\]", line)
        if header:
            section = sections.get(re.sub(r"[^a-z]", "", header.group(1).lower()))
            if section is None:
                problems.append(f"line {n}: unknown section {line} "
                                "(use [words], [phrases], [censored], [cut-off] or [replacements])")
            continue
        if section is None:
            continue
        if section == "replacements":
            swear, eq, clean = line.partition("=")
            pattern = [re.sub(r"[^a-z*]", "", w) for w in swear.lower().split()]
            clean = " ".join(clean.split())
            if not eq or not pattern or any(not p.replace("*", "") for p in pattern) or not re.search(r"[A-Za-z]", clean):
                problems.append(f"line {n}: a replacement is written as  swear = clean word  : {line}")
            else:
                replacements.append((pattern, clean))
            continue
        if section == "censored":
            try:
                re.compile(line)
                censored.append(line)
            except re.error as e:
                problems.append(f"line {n}: not a valid regular expression ({e}): {line}")
            continue
        entries = [re.sub(r"[^a-z*]", "", w) for w in line.lower().split()]
        entries = [e for e in entries if e]
        if not entries or any(not e.replace("*", "") for e in entries):
            problems.append(f"line {n}: every word needs at least one letter: {line}")
        elif section == "cutoff":
            cutoff += [e.replace("*", "") for e in entries]
        elif len(entries) == 1:
            words.append(entries[0])
        else:
            phrases.append(entries)
    if not problems and not words and not phrases:
        problems.append("the list has no words in it")
    rules = None if problems else Rules(words, phrases, censored, cutoff, source, replacements)
    if rules and replacements:   # a clean word that is itself on the list would put a swear back
        global RULES
        saved, RULES = globals().get("RULES"), rules       # find_hits reads the list in force
        try:
            for pattern, clean in replacements:
                if find_hits([(i, i + 0.5, w, *norm(w)) for i, w in enumerate(clean.split())]):
                    problems.append(f"the replacement for {' '.join(pattern)} is itself on the list: {clean}")
        finally:
            RULES = saved
    if problems:
        raise WordListError("\n".join(problems))
    return rules


RULES = parse_words(DEFAULT_WORDS, "built-in list")


def use_words(path=None):
    """Load the word list: the given file, else words.txt next to the program, else the built-in list."""
    global RULES
    p = Path(path) if path else HERE / "words.txt"
    if path and not p.is_file():
        sys.exit(f"word list not found: {p}")
    try:
        RULES = parse_words(read_text(p), str(p)) if p.is_file() else parse_words(DEFAULT_WORDS, "built-in list")
    except WordListError as e:
        sys.exit(f"Problem in the word list {p}:\n{e}")
    return RULES


INNOCENT_BEFORE = {"cum": ("laude",)}   # a word on the list that is innocent before these: "summa cum laude"


def match_len(toks, i, gap_ok=None):
    """How many tokens starting at i make up one profanity hit (0 = none). toks = [(raw, tok), ...]"""
    for ph in RULES.phrases:
        n = len(ph)
        chunk = toks[i:i + n]
        if len(chunk) == n and all(p.fullmatch(c[1]) for p, c in zip(ph, chunk)) \
           and (gap_ok is None or all(gap_ok(i + k) for k in range(n - 1))):
            return n
    raw, tok = toks[i]
    if tok in INNOCENT_BEFORE and i + 1 < len(toks) and toks[i + 1][1] in INNOCENT_BEFORE[tok]:
        return 0
    return 1 if RULES.words.fullmatch(tok) or RULES.censored.fullmatch(raw) else 0


def find_hits(words, tag=""):
    """words = [(start, end, text, raw, tok), ...]  ->  hits = [(start, end, text, tag), ...]"""
    toks = [w[3:] for w in words]
    gap_ok = lambda k: words[k + 1][0] - words[k][1] <= MAX_GAP
    hits, i = [], 0
    while i < len(words):
        n = match_len(toks, i, gap_ok)
        if n:
            hits.append((words[i][0], words[i + n - 1][1], " ".join(w[2] for w in words[i:i + n]), tag))
        i += n or 1
    return hits


# ---------------------------------------------------------------- models

def load_models():
    """The models the window offers, from models.txt next to the program: [(name, note), ...]"""
    def read(text):
        rows = [line.partition("|") for line in map(str.strip, text.splitlines()) if line and not line.startswith("#")]
        return [(name.strip(), note.strip()) for name, _, note in rows if name.strip()]
    p = HERE / "models.txt"
    return (read(read_text(p)) if p.is_file() else []) or read(DEFAULT_MODELS)


def list_models():
    """What the window shows for each model: is it on this PC already, and how big is the download.

    Where a model lives is faster-whisper's business, and its size Hugging Face's: both are asked
    here, nothing is hard-coded, so a moved or new model needs no change to ProfMute.
    """
    from faster_whisper import utils
    known = getattr(utils, "_MODELS", {})
    out = []
    for name, note in load_models():
        info = {"name": name, "note": note, "downloaded": False, "size": None, "problem": None}
        if os.path.isdir(name):
            info["downloaded"] = True
            info["size"] = sum(f.stat().st_size for f in Path(name).rglob("*") if f.is_file())
        else:
            repo = name if "/" in name else known.get(name)
            if repo is None:
                info["problem"] = "unknown model name"
            else:
                try:
                    utils.download_model(name, local_files_only=True)
                    info["downloaded"] = True
                except Exception:
                    pass
                try:
                    from huggingface_hub import HfApi
                    files = HfApi().model_info(repo, files_metadata=True, timeout=6).siblings
                    info["size"] = sum(f.size or 0 for f in files) or None
                except Exception:
                    pass  # offline, or the repository has moved: the size is simply unknown
        out.append(info)
    return out


def load_model(name, want):
    """Load a Whisper model on the NVIDIA GPU when there is a usable one, else on the CPU.

    -> (model, words describing where it runs)
    """
    import ctranslate2
    import numpy as np
    from faster_whisper import WhisperModel
    try:
        gpu = want != "cpu" and ctranslate2.get_cuda_device_count() > 0
    except Exception:
        gpu = False
    if want == "cuda" and not gpu:
        sys.exit("--device cuda: no NVIDIA GPU was found")
    why = "no NVIDIA GPU found"
    if gpu:
        try:
            kind = "float16" if "float16" in ctranslate2.get_supported_compute_types("cuda") else "default"
            model = WhisperModel(name, device="cuda", compute_type=kind)
            # the GPU libraries are only loaded on first use, so use it once before trusting it
            list(model.transcribe(np.zeros(SR, dtype=np.float32), language="en")[0])
            return model, "the NVIDIA GPU"
        except Exception as e:
            if want == "cuda":
                sys.exit(f"the NVIDIA GPU could not be used: {first_line(e)}")
            print(f"    The NVIDIA GPU could not be used: {first_line(e)}")
            why = "the NVIDIA GPU could not be used"
    try:
        model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=max(2, (os.cpu_count() or 4) // 2))
    except Exception as e:
        sys.exit(f"could not load the model '{name}': {first_line(e)}")
    return model, f"the CPU ({why}). This is much slower; a smaller model such as small.en will help"


def transcribe(model, samples, offset=0.0, progress=False, **kw):
    segs, info = model.transcribe(samples, language="en", word_timestamps=True,
                                  condition_on_previous_text=False, **kw)
    words = []
    for seg in segs:
        for w in seg.words:
            words.append((w.start + offset, w.end + offset, w.word.strip(), *norm(w.word)))
        if progress:
            print(f"\r    {min(100.0, seg.end / info.duration * 100):3.0f}%", end="", flush=True)
    if progress:
        print()
    return words


# ---------------------------------------------------------------- subtitles

def sidecar_srt(src):
    """The subtitle file sitting next to a movie (<name>.en.srt, .eng.srt or .srt), or None."""
    for suffix in (".en.srt", ".eng.srt", ".srt"):
        p = src.with_name(src.stem + suffix)
        if p.is_file():
            return p
    return None


def find_subtitle(src, tmp):
    """Sidecar .srt next to the movie, else an English text subtitle track inside it. (path, description)"""
    p = sidecar_srt(src)
    if p:
        return p, p.name
    r = run([FFPROBE, "-v", "error", "-select_streams", "s",
             "-show_entries", "stream=codec_name:stream_tags=language", "-of", "json", str(src)])
    streams = json.loads(r.stdout or "{}").get("streams", [])
    text = [k for k, s in enumerate(streams) if s.get("codec_name") in TEXT_SUBS]
    eng = [k for k in text if streams[k].get("tags", {}).get("language", "").lower() in ("en", "eng")]
    if not text:
        return None, None
    k = (eng or text)[0]
    p = Path(tmp) / "embedded.srt"
    run([FFMPEG, "-y", "-i", str(src), "-map", f"0:s:{k}", "-f", "srt", str(p)])
    return p, f"subtitle track {k} inside the file"


def parse_srt(path):
    """-> cues = [(start, end, text), ...]; text keeps its line breaks"""
    text = read_text(path)
    t = r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})"
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "")):
        m = re.search(t + r"\s*-->\s*" + t + r"[^\n]*\n(.*)", block, re.S)
        if m:
            g = m.groups()
            secs = lambda h, mi, s, ms: int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000
            lines = [ln.strip() for ln in g[8].split("\n")]
            cues.append((secs(*g[0:4]), secs(*g[4:8]), "\n".join(ln for ln in lines if ln)))
    return cues


def flat(text):
    """A cue on one line, for messages and the log."""
    return " ".join(TAGS.sub("", text).split())


def cue_scan(text):
    """Split one subtitle cue into words and find its profanity.

    -> (pieces = [(line number, word as written), ...],
        hits   = [(index of first piece, number of pieces, label), ...]; cut-off words get a '...' label)
    """
    pieces = [(n, p) for n, line in enumerate(text.split("\n")) for p in PIECE.findall(line)]
    toks = [norm(TAGS.sub("", p)) for _, p in pieces]
    hits, i = [], 0
    while i < len(toks):
        n = match_len(toks, i)
        if n:
            hits.append((i, n, " ".join(t[0] for t in toks[i:i + n])))
        elif RULES.cutoff.fullmatch(toks[i][1]) and re.search(r"(\.\.\.|…|-|—)\W*$", TAGS.sub("", pieces[i][1])):
            hits.append((i, 1, toks[i][0] + "..."))
        i += n or 1
    return pieces, hits


def cue_hits(text):
    """Profanity in one subtitle cue -> list of labels."""
    return [label for _, _, label in cue_scan(text)[1]]


def clean_cue(text, spoken=None, keep=(), delete=()):
    """One subtitle cue with its profanity deleted. -> (new text, '' if nothing is left; words deleted)

    The words are simply removed. A deleted word hands its sentence-ending punctuation to the word
    before it ("Oh, shit." -> "Oh."), and the next word is capitalized when the sentence now starts
    there ("Damn it." -> "It."). Lines and cues with no words left are dropped.
    spoken = {hit number in this cue: clean word said in its place}: those are swapped, not deleted
    ("Fuck no." -> "Heck no.").
    From the transcript review: keep = hit numbers left as they are; delete = phrases ([tok, ...]) deleted too, or
    swapped for a word said in their place: ([tok, ...], word).
    """
    pieces, hits = cue_scan(text)
    hits = [(h, x) for h, x in enumerate(hits) if h not in keep]       # numbered by their place in cue_scan
    toks = [norm(TAGS.sub("", p))[1] for _, p in pieces]
    taken = {x[0] + k for _, x in hits for k in range(x[1])}
    spoken = dict(spoken or {})
    for j, phrase in enumerate(delete):
        phrase, word = phrase if isinstance(phrase, tuple) else (phrase, None)
        n = len(phrase)
        i = next((i for i in range(len(toks) - n + 1) if toks[i:i + n] == list(phrase) and not taken & set(range(i, i + n))), None)
        if i is not None:
            hits.append((("said", j), (i, n, " ".join(phrase))))
            if word:
                spoken[("said", j)] = word
            taken |= set(range(i, i + n))
    if not hits:
        return text, 0
    swap = {i: (n, spoken[h]) for h, (i, n, _) in hits if h in spoken}
    absorbed = {i + k for i, (n, _) in swap.items() for k in range(1, n)}     # the rest of a swapped phrase
    drop = {i + k for h, (i, n, _) in hits if h not in spoken for k in range(n)}
    kept = []                # [line number, lead tags, body, trail tags] of the words that stay
    carry, capitalize = "", False   # tags/quotes owed to the next kept word; capitalize it?
    for i, (line, piece) in enumerate(pieces):
        lead, body, trail = SPLIT_TAGS.match(piece).groups()
        if i in absorbed:
            continue
        if i in swap:
            n, clean = swap[i]
            opening = re.match(r"[^\w*]*", body).group()
            closing = re.search(r"[^\w*]*$", SPLIT_TAGS.match(pieces[i + n - 1][1]).group(2)).group()
            said = body[len(opening):]
            if said[:2].isupper() and said[:2].isalpha():
                clean = clean.upper()
            elif said[:1].isupper():
                clean = clean[:1].upper() + clean[1:]
            body, trail = opening + clean + closing, SPLIT_TAGS.match(pieces[i + n - 1][1]).group(3)
        if i not in drop:
            if capitalize and body[:1].islower():
                body = body[:1].upper() + body[1:]
            if any(c.isalnum() for c in body):
                capitalize = False
            kept.append([line, carry + lead, body, trail])
            carry = ""
            continue
        prev = next((k for k in reversed(kept) if any(c.isalnum() for c in k[2])), None)
        after_dash = bool(kept) and not any(c.isalnum() for c in kept[-1][2])   # "- Shit!" opens a speaker's line
        starts_sentence = prev is None or after_dash or prev[2].rstrip(QUOTES)[-1:] in TERMINAL
        tail = re.search(r"[^\w*]*$", body).group()
        if starts_sentence:
            if body.lstrip(QUOTES + "-")[:1].isupper():
                capitalize = True
            carry += lead + body[:len(body) - len(body.lstrip(QUOTES))] + trail   # tags and an opening quote move on
        else:
            if any(c in TERMINAL for c in tail):
                prev[2] = prev[2].rstrip(",;:") + "".join(c for c in tail if c in TERMINAL + QUOTES)
            else:
                if tail[:1] in tuple(",;:") and prev[2][-1:] not in tuple(",;:-"):
                    prev[2] += tail[0]
                prev[2] += "".join(c for c in tail if c in QUOTES)
            prev[3] += lead + trail
    if carry and kept:
        kept[-1][3] += carry
    lines = {}
    for line, lead, body, trail in kept:
        lines.setdefault(line, []).append(lead + body + trail)
    out = [" ".join(words) for _, words in sorted(lines.items())]
    out = [ln for ln in out if any(c.isalnum() for c in TAGS.sub("", ln))]
    return "\n".join(out), len(hits) - len(swap)


def spoken_in_cues(cues, said):
    """Which subtitle swear each spoken clean word replaced.
    said = [(time, swear as Whisper heard it, clean word), ...] -> {(cue number, hit number in the cue): clean word}

    The cue nearest the time (subtitle times are loose, so up to 1.5 s off) whose next unclaimed swear is
    like the one heard ("fuckin'" / "fucking", "god damn" / "goddamn", "fucked" / "chest-fucked")."""
    out = {}
    key = lambda x: re.sub(r"[^a-z]", "", x.lower())
    for t, swear, clean in sorted(said):
        heard = key(swear)
        near = sorted((max(cs - t, t - ce, 0), k) for k, (cs, ce, _) in enumerate(cues) if cs - 1.5 <= t <= ce + 1.5)
        for _, k in near:
            found = next(((k, h) for h, (_, _, label) in enumerate(cue_scan(cues[k][2])[1])
                          if (k, h) not in out and key(label) and heard
                          and (heard[:4] in key(label) or key(label)[:4] in heard)), None)
            if found:
                out[found] = clean
                break
    return out


def picks_in_cues(cues, picks):
    """The transcript review's changes, as they apply to the subtitles: a kept word stays in its line, a muted
    phrase is deleted from it, or swapped for the word said in its place (a fourth item). The line is the one
    nearest the time (up to 1.5 s off, as in spoken_in_cues).
    -> {cue number: ({hit numbers kept}, [[tok, ...] deleted, or ([tok, ...], word said), ...])}"""
    out = {}
    key = lambda x: re.sub(r"[^a-z]", "", x.lower())
    near = lambda t: [k for _, k in sorted((max(cs - t, t - ce, 0), k) for k, (cs, ce, _) in enumerate(cues)
                                           if cs - 1.5 <= t <= ce + 1.5)]
    for s, e, word in picks.get("keep", []):
        heard = key(word)
        for k in near(s):
            kept = out.setdefault(k, (set(), []))[0]
            h = next((h for h, (_, _, label) in enumerate(cue_scan(cues[k][2])[1]) if h not in kept and heard and key(label)
                      and (heard[:4] in key(label) or key(label)[:4] in heard)), None)
            if h is not None:
                kept.add(h)
                break
    for s, e, words, *said in picks.get("mute", []):
        phrase = [tok for tok in (norm(w)[1] for w in words.split()) if tok]
        for k in near(s):
            toks = [norm(TAGS.sub("", p))[1] for _, p in cue_scan(cues[k][2])[0]]
            if phrase and any(toks[i:i + len(phrase)] == phrase for i in range(len(toks))):
                out.setdefault(k, (set(), []))[1].append((phrase, said[0]) if said and said[0] else phrase)
                break
    return out


def clean_srt(cues, spoken=None, picks=None):
    """-> (text of a subtitle file with the profanity deleted, words deleted, cues dropped as empty)
    spoken = {(cue number, hit number): clean word} from spoken_in_cues(): those words are swapped in instead.
    picks = the transcript review's changes (see apply_picks): kept words stay, muted phrases go too."""
    def t(x):
        ms = max(0, round(x * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    blocks, deleted, dropped = [], 0, 0
    changes = picks_in_cues(cues, picks) if picks else {}
    for k, (cs, ce, text) in enumerate(cues):
        keep, delete = changes.get(k, ((), ()))
        new, n = clean_cue(text, {h: w for (c, h), w in (spoken or {}).items() if c == k}, keep, delete)
        deleted += n
        if new:
            blocks.append(f"{len(blocks) + 1}\n{t(cs)} --> {t(ce)}\n{new}\n")
        else:
            dropped += 1
    return "\n".join(blocks), deleted, dropped


def estimate_offset(cues, words, search=OFFSET_SEARCH):
    """Guess how far the subtitles are shifted from the audio (looking up to `search` seconds either way).

    Each line votes with (when Whisper heard the line's first word) - (line start); the most popular
    shift wins. Returns (seconds to add to subtitle times, share of lines agreeing), or (0.0, None)
    when there are too few lines to tell.
    """
    starts = [w[0] for w in words]
    votes, voters = Counter(), 0
    for cs, _, text in cues:
        pieces = TAGS.sub("", text).split()
        tok = norm(pieces[0])[1] if pieces else ""
        if len(tok) < 3:
            continue
        lo = bisect.bisect_left(starts, cs - search)
        hi = bisect.bisect_right(starts, cs + search)
        bins = {round((w[0] - cs) / OFFSET_BIN) for w in words[lo:hi] if w[4] == tok}
        if bins:
            voters += 1
            votes.update(bins)
    if voters < 20:
        return 0.0, None
    best = max(votes, key=lambda b: votes[b - 1] + votes[b] + votes[b + 1])
    near = [(b, votes[b]) for b in (best - 1, best, best + 1)]
    support = sum(n for _, n in near)
    return sum(b * n for b, n in near) * OFFSET_BIN / support, support / voters


def match_subs(expected, hits):
    """Pair subtitle hits with Whisper hits (each Whisper hit is used once, closest lines first).

    expected = [(line_start, line_end, label, cue_index), ...]; hits must be sorted by time.
    -> (subtitle hits no Whisper hit accounts for, indexes of the Whisper hits the subtitles back up)
    """
    used, left = set(), expected
    for tol in (0.3, SRT_TOL):
        still = []
        for ex in left:
            j = next((j for j, h in enumerate(hits) if j not in used
                      and ex[0] - tol <= (h[0] + h[1]) / 2 <= ex[1] + tol), None)
            if j is None:
                still.append(ex)
            else:
                used.add(j)
        left = still
    return left, used


def missing(expected, hits):
    """Subtitle hits with no Whisper hit of their own."""
    return match_subs(expected, hits)[0]


def subtitle_hits(cues):
    return [(cs, ce, label, k) for k, (cs, ce, text) in enumerate(cues) for label in cue_hits(text)]


def subtitle_pass(model, samples, cues, hits, voice_band=None):
    """Re-listen around subtitle lines whose profanity Whisper missed.

    Up to three tries per line: a plain second listen, one where Whisper is shown the subtitle
    line, and one on a filtered copy of the sound (voice_band() returns it; it is only asked for
    when the first two tries fail somewhere). Different preparations of the same sound make Whisper
    miss different words, so the third try finds some the first two cannot.
    Returns (all hits, subtitle hits still not found, how many lines were re-listened to).
    """
    expected = subtitle_hits(cues)
    todo = sorted({ex[3] for ex in missing(expected, hits)})
    filtered = None
    for n, k in enumerate(todo, 1):
        cs, ce, text = cues[k]
        print(f"\r    re-listening {n}/{len(todo)}", end="", flush=True)
        s = max(0.0, cs - RESCAN_PAD)
        window = slice(int(s * SR), int((ce + RESCAN_PAD) * SR))
        for kind, prompt, tag in (("plain", None, "pass 2"), ("plain", flat(text), "pass 2, subtitle hint"),
                                  ("filtered", None, "pass 2, filtered audio")):
            if kind == "filtered":
                if voice_band is None:
                    break
                if filtered is None:
                    filtered = voice_band()
            found = find_hits(transcribe(model, (samples if kind == "plain" else filtered)[window], s,
                                         initial_prompt=prompt), tag)
            new = [h for h in found if not any(overlaps(h, x) for x in hits)]
            hits = sorted(hits + new)
            if not any(ex[3] == k for ex in missing(expected, hits)):
                break
    if todo:
        print()
    return hits, missing(expected, hits), len(todo)


# ---------------------------------------------------------------- second listens and conflicts

def overlaps(a, b, slack=0.15):
    return a[0] < b[1] + slack and b[0] < a[1] + slack


def same_word(a, b):
    """bullshit / shit, goddamn / God damn: the same word as far as a second listen is concerned."""
    a, b = (re.sub(r"[^a-z]", "", x.lower()) for x in (a, b))
    return bool(a and b) and (a in b or b in a)


def agrees(a, b):
    """Two placements of a word agree when they share at least half of the shorter one."""
    la, lb = max(a[1] - a[0], 0.1), max(b[1] - b[0], 0.1)
    return min(a[0] + la, b[0] + lb) - max(a[0], b[0]) >= 0.5 * min(la, lb)


def vote(model, samples, hit, others):
    """Listen to one hit a second and, if the two disagree, a third time.

    -> (verdict, spans, heard)
       'confirmed': two listens put the word where the hit is; spans = the hit, unchanged
       'moved':     two listens agree it is somewhere else nearby; spans = that place
       'unsure':    no two listens agree; spans = every place it was heard
       heard = how many listens heard it at all, e.g. "1 of 3"
    """
    elsewhere, heard, listens = [], 1, 1
    for before, after in LISTENS:
        listens += 1
        s = max(0.0, hit[0] - before)
        clip = samples[int(s * SR):int((hit[1] + after) * SR)]
        found = find_hits(transcribe(model, clip, s))
        free = [p for p in found if not any(overlaps(p, o, 0) for o in others)]   # not some other known word
        here = [p for p in found if agrees(p, hit) and same_word(p[2], hit[2])] or [p for p in free if agrees(p, hit)]
        there = [p for p in free if not agrees(p, hit) and same_word(p[2], hit[2])]
        heard += bool(here or there)
        if here:
            return "confirmed", [hit[:2]], f"{heard} of {listens}"
        agree = [(a, t) for a in elsewhere for t in there if agrees(a, t)]
        if agree:
            a, t = agree[0]
            return "moved", [(min(a[0], t[0]), max(a[1], t[1]))], f"{heard} of {listens}"
        elsewhere += there
    return "unsure", [hit[:2]] + [p[:2] for p in elsewhere], f"{heard} of {listens}"


def ask_user(info):
    """Put one question to the user, in the terminal or (as one line of JSON) to the window.

    A conflict (info['kind'] == 'conflict'): -> 'mute', 'leave', or 'auto' (three listens decide this and the rest)
    An unresolved word ('unresolved'):       -> 'line', 'spot', 'leave', or 'auto' (leave this and the rest)
    And, when info['can_go_back']: 'back' (to the question before, to answer it again)
    """
    unresolved = info.get("kind") == "unresolved"
    back = bool(info.get("can_go_back"))
    if sys.stdin is not None and sys.stdin.isatty():
        if unresolved:
            print(f"\nUNRESOLVED {info['n']} of {info['of']} at {info['time']}: the subtitles have \"{info['word']}\", "
                  f"Whisper did not hear it.")
            print(f"    Subtitle line: {info['line']}  ({info['line_seconds']:.1f} s)")
            print(f"    Whisper heard: {info['heard'] or '(nothing)'}")
            print(f"    Best guess at the spot: {info['spot']}  ({info['spot_seconds']:.1f} s)")
            keys, question = {"w": "line", "s": "spot", "l": "leave", "r": "auto"}, \
                "    mute the [w]hole line, only the estimated [s]pot, [l]eave it, or leave this and the [r]est"
        else:
            print(f"\nCONFLICT {info['n']} of {info['of']} at {info['time']}: Whisper heard \"{info['word']}\", "
                  f"the subtitles do not have it.")
            print(f"    Whisper:   {info['before']} >>{info['word']}<< {info['after']}")
            print(f"    Subtitles: {info['subtitles'] or '(nothing at that moment)'}")
            keys, question = {"m": "mute", "l": "leave", "r": "auto"}, \
                "    [m]ute it, [l]eave it, or let three listens decide this and the [r]est"
        if info.get("previous"):
            print(f"    You answered before: {info['previous']}")
        if back:
            keys["b"], question = "back", question + ", or go [b]ack to the one before"
        question += "? "
        while True:
            answer = input(question).strip().lower()[:1]
            if answer in keys:
                return keys[answer]
    print(ASK + json.dumps(info), flush=True)
    answer = sys.stdin.readline().strip() if sys.stdin is not None else ""
    allowed = (("line", "spot", "leave") if unresolved else ("mute", "leave")) + (("back",) if back else ())
    return answer if answer in allowed else "auto"


def ask_all(questions):
    """Ask the questions one after another, with a way back: questions = [("conflicts" | "unresolved", info), ...].
    'auto' answers the rest of its kind too; 'back' reopens the question answered before (showing that answer).
    -> {"conflicts": {n: answer}, "unresolved": {n: answer}}"""
    answers, asked, i = {"conflicts": {}, "unresolved": {}}, [], 0
    while i < len(questions):
        part, info = questions[i]
        answer = ask_user(dict(info, can_go_back=bool(asked), previous=answers[part].get(info["n"])))
        if answer == "back" and asked:
            i = asked.pop()
            continue
        answers[part][info["n"]] = answer
        asked.append(i)
        i += 1
        if answer == "auto":   # the rest of this kind is decided too: on to the other kind, if any
            while i < len(questions) and questions[i][0] == part:
                answers[part].pop(questions[i][1]["n"], None)
                i += 1
    return answers


def save_clip(path, samples, start, end):
    """A stretch of the sound as a WAV file, for the window's Play buttons."""
    import wave
    import numpy as np
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        part = samples[max(0, int(start * SR)):int(end * SR)]
        wf.writeframes((np.clip(part, -1, 1) * 32767).astype(np.int16).tobytes())
    return path


def estimate_spot(cue, first, count, words):
    """Guess when, inside a subtitle line, a word Whisper did not hear was said. -> (start, end)

    cue = (start, end, text); the word is pieces first .. first+count-1 of the line (see cue_scan).
    The words of the line Whisper did hear are the landmarks: the missing one lies between the
    heard word before it and the heard word after it. With no landmarks, its place in the line's
    text is used as its place in the line's time, which is rougher.
    """
    cs, ce, text = cue
    toks = [norm(TAGS.sub("", p))[1] for _, p in cue_scan(text)[0]]
    near = [w for w in words if w[0] >= cs - 1.0 and w[1] <= ce + 1.0]
    landmarks, j = {}, 0
    for i, tok in enumerate(toks):
        if tok and not first <= i < first + count:
            k = next((k for k in range(j, len(near)) if near[k][4] == tok), None)
            if k is not None:
                landmarks[i], j = near[k], k + 1
    before = max((i for i in landmarks if i < first), default=None)
    after = min((i for i in landmarks if i >= first + count), default=None)
    size = lambda a, b: sum(len(t) + 1 for t in toks[a:b])        # letters, a stand-in for speaking time
    length = min(1.5, 0.3 + 0.07 * size(first, first + count))    # how long saying the word probably takes
    if before is not None and after is not None:
        lo, hi = landmarks[before][1], landmarks[after][0]
        if after - before - 1 == count and hi - lo >= 0.15:       # the word has the gap to itself: the gap is the spot
            return max(0.0, lo - 0.1), hi + 0.1
        # other unheard words share the gap (or Whisper left none): place it by its share of the letters
        middle = lo + (hi - lo) * (size(before + 1, first) + size(first, first + count) / 2) / (size(before + 1, after) or 1)
    elif before is not None:
        middle = landmarks[before][1] + 0.07 * size(before + 1, first) + length / 2
    elif after is not None:
        middle = landmarks[after][0] - 0.07 * size(first + count, after) - length / 2
    else:
        middle = cs + (ce - cs) * (size(0, first) + size(first, first + count) / 2) / (size(0, len(toks)) or 1)
    middle = min(max(middle, cs - 0.5), ce + 0.5)
    return max(0.0, middle - length / 2 - 0.25), middle + length / 2 + 0.25   # a quarter second of margin: it is a guess


def unresolved_questions(samples, words, cues, unresolved, clips=None):
    """One question per word that is in the subtitles but was never heard, with the estimated spot.
    unresolved = [(line_start, line_end, label, cue_index), ...]; clips = a folder for the Play clips, or None.
    -> [{"info": the question, "line": (start, end), "spot": (start, end), "label": the word}, ...]"""
    out, used = [], set()
    for n, (cs, ce, label, k) in enumerate(unresolved):
        scan = cue_scan(cues[k][2])[1]
        at = next((x for x in range(len(scan)) if scan[x][2] == label and (k, x) not in used), 0)
        used.add((k, at))
        first, count = scan[at][:2] if scan else (0, 1)
        s, e = estimate_spot(cues[k], first, count, words)
        info = {"kind": "unresolved", "n": n + 1, "of": len(unresolved), "time": stamp(cs), "word": label,
                "line": flat(cues[k][2]), "line_seconds": ce - cs,
                "heard": " ".join(w[2] for w in words if w[0] >= cs - 0.5 and w[1] <= ce + 0.5),
                "spot": f"{stamp(s)} to {stamp(e)}", "spot_seconds": e - s, "clip": None, "clip_spot": None}
        if clips:   # the window can play both stretches
            info["clip"] = save_clip(os.path.join(clips, f"line{n + 1}.wav"), samples, cs - 0.75, ce + 0.75)
            info["clip_spot"] = save_clip(os.path.join(clips, f"spot{n + 1}.wav"), samples, s, e)
        out.append({"info": info, "line": [cs, ce], "spot": [s, e], "label": label})
    return out


def apply_unresolved(questions, answers):
    """answers = {question number: 'line' / 'spot' / 'leave' / 'auto' (leave this and the rest)}; a question
    left unanswered is left in. -> (spans to mute [(start, end, text, tag), ...], {index: what was decided})"""
    mute, decided, rest = [], {}, False
    for n, q in enumerate(questions):
        answer = answers.get(q["info"]["n"])
        (cs, ce), (s, e), label = q["line"], q["spot"], q["label"]
        if rest:
            decided[n] = "left in (your choice: leave the rest)"
        elif answer == "line":
            mute.append((cs, ce, label, "unresolved: you muted the whole subtitle line"))
            decided[n] = "whole line muted (your choice)"
        elif answer == "spot":
            mute.append((s, e, label, "unresolved: you muted an estimated spot"))
            decided[n] = f"estimated spot {stamp(s)} muted (your choice)"
        elif answer in ("leave", "auto"):
            decided[n] = "left in (your choice)"
            rest = answer == "auto"
        else:
            decided[n] = "left in (not answered)"
    return mute, decided


def decide_unresolved(samples, words, cues, unresolved):
    """Ask the user now about each word that is in the subtitles but was never heard.
    -> (spans to mute [(start, end, text, tag), ...], {index in unresolved: what was decided, for the log})
    """
    window = sys.stdin is None or not sys.stdin.isatty()
    clips = tempfile.mkdtemp(prefix="profmute-") if window else None
    try:
        questions = unresolved_questions(samples, words, cues, unresolved, clips)
        return apply_unresolved(questions, ask_all([("unresolved", q["info"]) for q in questions])["unresolved"])
    finally:
        if clips:
            shutil.rmtree(clips, ignore_errors=True)


def conflict_outcome(answer, where, s, e, text, get_vote):
    """What one conflict comes to, given the answer ('mute', 'leave', or anything else: the listens decide).
    -> (spans to mute [(start, end, text, tag)], the line for the log). get_vote() -> (verdict, spans, heard)."""
    line = f"{stamp(where[0])}  {text}"
    if answer == "mute":
        return [(where[0], where[1], text, "conflict: you chose to mute")], line + "  ->  muted (your choice)"
    if answer == "leave":
        return [], line + "  ->  left in (your choice)"
    verdict, spans, heard = get_vote()
    if verdict == "unsure":
        times, of = heard.split(" of ")
        why = "heard in a different place on every listen" if times == of else \
              f"heard in {heard} listens, but never twice in the same place" if int(times) > 1 else \
              f"heard in only {heard} listens"
        return [], f"{stamp(s)}  {text}  ->  left in ({why})"
    return [(a, b, text, f"conflict: heard in {heard} listens") for a, b in spans], \
        f"{stamp(spans[0][0])}  {text}  ->  muted (heard in {heard} listens)"


def resolve_conflicts(pending, answers):
    """The conflicts saved for later (settle(..., conflicts='later')), with the answers given since.
    answers = {question number: 'mute' / 'leave' / 'auto'}; 'auto' lets the listens decide this one and the
    rest, as does a question left unanswered. -> (spans to mute, lines for the log)"""
    mute, report, auto = [], [], False
    for p in pending:
        answer = "auto" if auto else answers.get(p["info"]["n"], "auto")
        auto = auto or answer == "auto"
        spans, line = conflict_outcome(answer, p["where"], p["s"], p["e"], p["text"], lambda p=p: p["vote"])
        mute += [tuple(x) for x in spans]
        report.append(line)
    return mute, report


def settle(model, samples, hits, words, cues, backed, confirm, conflicts, dry, clips_dir=None):
    """Decide what is muted: optional second listens for every hit, then the conflicts.

    hits    = [(start, end, text, tag), ...] sorted by time
    backed  = indexes of the hits the subtitles back up, or None when no subtitles are in use
    conflicts = 'ask' (now), 'auto' (the listens decide) or 'later': each conflict becomes a question saved for
              later (see resolve_conflicts), its Play clip kept in clips_dir
    -> (hits to mute, conflict lines for the log, Counter of what happened, the questions saved for later)
    """
    is_conflict = lambda i: backed is not None and i not in backed
    later = conflicts == "later" and not dry
    asking = conflicts == "ask" and not dry
    votes, stats, mute, report, pending = {}, Counter(), [], [], []   # stats: how many votes ended confirmed/moved/unsure

    def get_vote(i):
        if i not in votes:
            votes[i] = vote(model, samples, hits[i], hits[:i] + hits[i + 1:])
        return votes[i]

    need = [i for i in range(len(hits)) if confirm or (is_conflict(i) and conflicts in ("auto", "later", "ask"))]
    for n, i in enumerate(need, 1):
        print(f"\r    listening again {n}/{len(need)}", end="", flush=True)
        get_vote(i)
    if need:
        print()

    todo = [i for i in range(len(hits)) if is_conflict(i)]
    clips = None
    for i, (s, e, text, tag) in enumerate(hits):
        verdict, spans, heard = votes.get(i, ("confirmed", [(s, e)], None))
        if not is_conflict(i):
            if verdict == "moved":
                tag = (tag + ", " if tag else "") + f"moved from {stamp(s)} by a second listen"
            elif verdict == "unsure":
                tag = (tag + ", " if tag else "") + ("position uncertain, every place heard is muted" if len(spans) > 1
                                                    else "not heard again on a second listen")
            mute += [(a, b, text, tag) for a, b in spans]
            continue

        # a hit the subtitles do not have
        where = spans[0] if verdict != "unsure" else (s, e)
        line = f"{stamp(where[0])}  {text}"
        if dry and conflicts == "ask":
            report.append(line + "  ->  would ask you (preview)")
            mute.append((where[0], where[1], text, "conflict: you would be asked"))
            stats["conflict"] += 1
            continue
        answer = "auto"
        if asking or later:
            near = [w for w in words if s - 4 <= w[0] <= e + 4]
            before = " ".join(w[2] for w in near if w[1] <= s + 0.01)
            after = " ".join(w[2] for w in near if w[0] >= e - 0.01)
            info = {"kind": "conflict", "n": todo.index(i) + 1, "of": len(todo), "time": stamp(where[0]), "word": text,
                    "before": before if len(before) <= 80 else "... " + before[-80:].partition(" ")[2],
                    "after": after if len(after) <= 80 else after[:80].rpartition(" ")[0] + " ...",
                    "subtitles": "  /  ".join(flat(c[2]) for c in cues if c[0] < e + 3 and c[1] > s - 3),
                    "listens": f"heard in {heard} listens" if heard else None, "clip": None}
            if clips_dir if later else sys.stdin is None or not sys.stdin.isatty():   # the window can play a few seconds
                clips = clips_dir if later else clips or tempfile.mkdtemp(prefix="profmute-")
                info["clip"] = save_clip(os.path.join(clips, f"conflict{info['n']}.wav"), samples,
                                         where[0] - 3, where[1] + 3)
            pending.append({"info": info, "where": list(where), "s": s, "e": e, "text": text, "vote": get_vote(i)})
            stats["conflict"] += 1
            continue
        spans, line = conflict_outcome(answer, where, s, e, text, lambda i=i: get_vote(i))
        mute += spans
        report.append(line)
        stats["conflict"] += 1
    if asking and pending:   # asked now, all of them, with a way back: the answers count once all are given
        more, lines = resolve_conflicts(pending, ask_all([("conflicts", p["info"]) for p in pending])["conflicts"])
        mute, report, pending = mute + more, report + lines, []
    if clips and not later:
        shutil.rmtree(clips, ignore_errors=True)
    stats.update(v[0] for v in votes.values())
    return sorted(mute), report, stats, pending


# ---------------------------------------------------------------- analysing now, writing later

REVIEW_VERSION = 1   # of the saved analysis: one saved by another version is analysed again


def movie_identity(src):
    st = Path(src).stat()
    return {"path": os.path.normcase(str(Path(src).resolve())), "size": st.st_size, "mtime": int(st.st_mtime)}


def analysis_settings(a, src, rules, model_name):
    """Everything an analysis depends on: a saved analysis is reused only when all of it is still the same."""
    words = Path(rules.source)
    text = words.read_bytes() if words.is_file() else DEFAULT_WORDS.encode()
    return {"version": REVIEW_VERSION, "movie": movie_identity(src), "model": model_name,
            "words": hashlib.sha1(text).hexdigest(), "confirm": a.confirm, "conflicts": a.conflicts,
            "unresolved": a.unresolved, "srt": a.srt, "no_srt": a.no_srt, "audio_index": a.audio_index}


def review_clips(path):
    """The folder for a saved analysis's Play clips, next to it."""
    return str(Path(path).with_suffix("")) + "-clips"


def review_is_current(path, settings):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("settings") == settings
    except (OSError, ValueError):
        return False


def save_review(path, state):
    """Written whole or not at all: the window adds the answers to the same file later."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    os.replace(tmp, p)


def load_review(path, src):
    try:
        state = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        sys.exit(f"The saved analysis {path} cannot be read ({first_line(e)}). Analyse the movie again.")
    if state.get("movie") != movie_identity(src):
        sys.exit("The movie file has changed since it was analysed. Analyse it again.")
    return state


def review_mutes(state):
    """What a saved analysis mutes, with the answers given since (before any changes made in the transcript).
    -> (hits [(start, end, text, tag)], conflict lines for the log, {unresolved index: what was decided})"""
    answers = state.get("answers", {})
    more, resolved = resolve_conflicts(state["pending"], {int(k): v for k, v in answers.get("conflicts", {}).items()})
    unmute, decided = apply_unresolved(state["questions"], {int(k): v for k, v in answers.get("unresolved", {}).items()})
    return sorted([tuple(h) for h in state["hits"]] + more + unmute), sorted(state["conflict_lines"] + resolved), decided


PICKED = "you picked it in the transcript"   # the tag of a spot muted from the transcript review
SAID = "you chose a word to say for it in the transcript"   # ... muted, with your word said in its place


def apply_picks(hits, picks, speak=False):
    """The changes made in the transcript: picks = {"mute": [[start, end, words(, word to say)], ...],
    "keep": [[start, end, word], ...]}. A kept word un-mutes every spot it overlaps; a picked one is muted where
    Whisper heard it, and with speak, your word for it is said there (the speaking step takes it from picks).
    -> (hits, lines for the log)"""
    keep, mute = [tuple(k) for k in picks.get("keep", [])], [tuple(m) for m in picks.get("mute", [])]
    said = lambda m: speak and len(m) > 3 and m[3]
    out = [h for h in hits if not any(h[0] < k[1] and k[0] < h[1] for k in keep)]
    out += [(m[0], m[1], m[2], SAID if said(m) else PICKED) for m in mute]
    lines = sorted([f'{stamp(m[0])}  {m[2]}  ->  say "{m[3]}" (your word; muted if it does not come out right)' if said(m)
                    else f"{stamp(m[0])}  {m[2]}  ->  muted (you picked it)" for m in mute] +
                   [f"{stamp(s)}  {text}  ->  kept (you un-muted it)" for s, e, text in keep])
    return sorted(out), lines


def drop_review(path):
    """After the clean copy is written, its saved analysis and clips are no longer needed."""
    shutil.rmtree(review_clips(path), ignore_errors=True)
    try:
        os.remove(path)
    except OSError:
        pass


def analyse(a, src, out, out_srt, model_name, rules, later, clips):
    """Steps 1-3: listen, check against the subtitles, settle each word. later = save the questions instead of
    asking them now (their Play clips go in `clips`). -> (state, the Whisper model). The state is plain data
    (it can be saved as JSON): words, cues, usable, notes, hits, conflict_lines, unresolved, decided,
    pending (conflict questions), questions (unresolved-word questions), out_srt, model."""
    print("1/4 Extracting audio...")
    samples = load_audio(src, a.audio_index)
    cues, srt_name, usable_cues = [], None, []
    with tempfile.TemporaryDirectory() as tmp:
        if not a.no_srt:
            srt, srt_name = (Path(a.srt), a.srt) if a.srt else find_subtitle(src, tmp)
            if srt:
                cues = parse_srt(srt)
                if out_srt.resolve() == srt.resolve():  # never write over the subtitle file we read
                    if a.out_srt:
                        sys.exit("the clean subtitle file is the subtitle file being read; pick a different name")
                    out_srt = out.with_name(out.stem + ".clean.en.srt")

    print(f"2/4 Transcribing with {model_name} (its first use downloads the model)...")
    model, where = load_model(model_name, a.device)
    print(f"    Running on {where}.")
    words = transcribe(model, samples, progress=True)
    hits = find_hits(words)

    notes, unresolved, backed = [f"Word list: {rules.source} ({rules.summary}). Model: {model_name}."], [], None
    if not cues:
        print("3/4 No subtitles found, skipping the double-check.")
        notes.append("Subtitles: none found, Whisper only.")
    else:
        print(f"3/4 Double-checking against subtitles ({srt_name})...")
        offset, agree = estimate_offset(cues, words)
        if agree is not None and agree < MIN_AGREEMENT:     # made for a release that starts a little differently?
            wide = estimate_offset(cues, words, OFFSET_SEARCH_WIDE)
            if wide[1] is not None and wide[1] >= MIN_AGREEMENT:
                offset, agree = wide
        if agree is not None and agree < MIN_AGREEMENT:
            print(f"    These subtitles do not line up with the audio (only {agree:.0%} of lines agree). Ignoring them.")
            notes.append(f"Subtitles: {srt_name} does NOT match this audio, ignored. Whisper only.")
        else:
            if abs(offset) < 0.5:
                offset = 0.0
            else:
                print(f"    Subtitles are {abs(offset):.1f}s {'early' if offset > 0 else 'late'}, shifting them to match.")
                cues = [(max(0.0, cs + offset), ce + offset, text) for cs, ce, text in cues
                        if ce + offset > 0]     # a line shifted to before the start can't be heard: dropped
            usable_cues = cues
            before = len(hits)
            hits, unresolved, relistened = subtitle_pass(model, samples, cues, hits,
                                                         lambda: load_audio(src, a.audio_index, VOICE_BAND))
            backed = match_subs(subtitle_hits(cues), hits)[1]
            print(f"    {relistened} line(s) re-listened to, {len(hits) - before} more hit(s) found, "
                  f"{len(unresolved)} unresolved.")
            sync = f"shifted {offset:+.1f}s" if offset else "in sync"
            notes.append(f"Subtitles: {srt_name}, {sync}. {relistened} line(s) re-listened to, "
                         f"{len(hits) - before} more hit(s) found, {len(unresolved)} unresolved.")

    # questions to ask now (not later) are collected first and asked together, conflicts then unresolved words,
    # with a way back through all of them; their answers count once every one is given
    now = not later and not a.dry
    window = sys.stdin is None or not sys.stdin.isatty()
    ask_conflicts = a.conflicts == "ask" and not a.dry
    ask_unresolved = bool(unresolved) and a.unresolved == "ask" and not a.dry
    if now and (ask_conflicts or ask_unresolved) and window:
        clips = tempfile.mkdtemp(prefix="profmute-")
    conflicts = "later" if ask_conflicts else a.conflicts
    hits, conflict_lines, stats, pending = settle(model, samples, hits, words, cues, backed, a.confirm, conflicts,
                                                  a.dry, clips)
    if a.confirm:
        print(f"    Second listens: {stats['confirmed']} confirmed, {stats['moved']} moved, {stats['unsure']} uncertain.")
        notes.append(f"Second listens: {stats['confirmed']} confirmed, {stats['moved']} moved, "
                     f"{stats['unsure']} uncertain.")
    if conflict_lines or pending:
        print(f"    {len(conflict_lines) + len(pending)} conflict(s): heard by Whisper, not in the subtitles.")
    decided, questions = {}, []
    if unresolved and a.unresolved == "ask" and a.dry:
        decided = {n: "would ask you (preview)" for n in range(len(unresolved))}
    elif ask_unresolved:
        questions = unresolved_questions(samples, words, cues, unresolved, clips)
    if now and (pending or questions):
        try:
            answers = ask_all([("conflicts", p["info"]) for p in pending] + [("unresolved", q["info"]) for q in questions])
        finally:
            if clips:
                shutil.rmtree(clips, ignore_errors=True)
        more, resolved = resolve_conflicts(pending, answers["conflicts"])
        unmute, decided = apply_unresolved(questions, answers["unresolved"])
        hits, conflict_lines = sorted(hits + more + unmute), sorted(conflict_lines + resolved)
        pending, questions = [], []
    state = dict(words=[list(w) for w in words], cues=[list(c) for c in cues], usable=bool(usable_cues), notes=notes,
                 hits=[list(h) for h in hits], conflict_lines=conflict_lines, unresolved=[list(u) for u in unresolved],
                 decided=decided, pending=pending, questions=questions, out_srt=str(out_srt), model=model_name, say=[])
    if later and a.speak and not a.no_separate:
        model = None                  # Whisper is done: the graphics card is for Gemma now
        gc.collect()
        state["say"] = choose_clean_words(state, usable_cues)
    return state, model


def choose_clean_words(state, usable_cues):
    """With "Speak a clean word", while listening for later: Gemma's clean word for every swear that could be
    spoken (the conflicts as if muted), so the transcript review can show them and you can change them.
    -> [[start, end, swear, clean word, chosen by], ...]; [] when they cannot be chosen now (then: when writing)."""
    import torch
    if not torch.cuda.is_available():
        return []
    torch.cuda.empty_cache()
    import speak
    spots = sorted([tuple(h[:3]) for h in state["hits"]] + [(p["where"][0], p["where"][1], p["text"]) for p in state["pending"]])
    sentences = speak.plan_sentences([(s, e, w, n) for n, (s, e, w) in enumerate(spots)], state["words"], usable_cues)
    try:
        speak.choose_words(sentences, sys.modules[__name__])
    except Exception as e:
        print(f"    The clean words could not be chosen now ({first_line(e)}); they will be when the clean copy is written.")
        return []
    return [[s["hit"][j][0], s["hit"][j][1], " ".join(w[2] for w in s["words"][f:l + 1]), s["picks"][j], s["chosen_by"][j]]
            for s in sentences if not s["muted"] and s.get("picks") for j, (f, l) in enumerate(s["swears"])]


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Mute profanity in a video's main audio track.")
    ap.add_argument("file", nargs="?", help="the movie")
    ap.add_argument("--dry", action="store_true", help="only list hits, write no video")
    ap.add_argument("--model", help="Whisper model (default: the first line of models.txt)")
    ap.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto",
                    help="auto = the NVIDIA GPU when there is one, else the CPU")
    ap.add_argument("--audio-index", type=int, default=0, help="which audio stream to clean (0 = first)")
    ap.add_argument("--srt", help="subtitle file to double-check against (default: auto-detect)")
    ap.add_argument("--no-srt", action="store_true", help="skip the subtitle double-check")
    ap.add_argument("--words", help="word list file (default: words.txt next to this program)")
    ap.add_argument("--out", help="where to write the clean copy (default: <name>.clean.mkv next to the movie)")
    ap.add_argument("--out-srt", help="where to write the clean subtitles (default: <clean copy name>.en.srt next to it)")
    ap.add_argument("--log-dir", help='folder for the log (default: a "log" folder next to this program)')
    ap.add_argument("--pad-before", type=float, default=PAD_BEFORE, help="seconds muted before each word")
    ap.add_argument("--pad-after", type=float, default=PAD_AFTER, help="seconds muted after each word")
    ap.add_argument("--no-fade", action="store_true",
                    help=f"switch each mute on and off instantly, instead of fading over {FADE * 1000:.0f} ms just around it")
    ap.add_argument("--all-channels", action="store_true",
                    help="mute every channel of a surround track, not just its centre (dialogue) channel")
    ap.add_argument("--no-front-check", action="store_true",
                    help="do not listen for the words in the front left/right speakers of a surround track")
    ap.add_argument("--no-separate", action="store_true",
                    help="silence the words instead of removing only the voice with an AI voice model")
    ap.add_argument("--speak", action="store_true",
                    help="say a clean word in the actor's own voice instead of muting a swear in normal speech "
                         "(shouts stay muted). Needs an NVIDIA graphics card; downloads about 14 GB on first use")
    ap.add_argument("--voice-model", help="voice model to use (default: the first line of voice-models.txt)")
    ap.add_argument("--list-voice-models", action="store_true", help="print the models of voice-models.txt as JSON and exit")
    ap.add_argument("--confirm", action="store_true", help="listen to every word a second time to check where it is")
    ap.add_argument("--conflicts", choices=("ask", "auto"), default="auto",
                    help="a word the subtitles do not have: ask = you decide, auto = three listens decide")
    ap.add_argument("--unresolved", choices=("ask", "leave"), default="leave",
                    help="a subtitle word that was never heard: ask = you decide (mute the line, an estimated "
                         "spot, or nothing), leave = list it in the log and mute nothing")
    ap.add_argument("--review-file", help="analyse only: save the questions (conflicts, unresolved words) to this "
                                          "file, to be answered later, and write nothing else")
    ap.add_argument("--from-review", help="write the clean copy from an analysis saved with --review-file, with the "
                                          "answers added to it since; unanswered questions are decided as without asking")
    ap.add_argument("--list-models", action="store_true", help="print the models of models.txt as JSON and exit")
    ap.add_argument("--version", action="version", version=f"ProfMute {__version__}")
    a = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")
    if a.list_models:
        return print(json.dumps(list_models()))
    if a.list_voice_models:
        return print(json.dumps(list_voice_models()))
    if not a.file:
        ap.error("which movie?")
    if a.pad_before < 0 or a.pad_after < 0:
        sys.exit("padding cannot be negative")

    src = Path(a.file)
    if not src.is_file():
        sys.exit(f"file not found: {src}")
    if a.srt and not Path(a.srt).is_file():
        sys.exit(f"subtitle file not found: {a.srt}")
    out = Path(a.out) if a.out else src.with_name(src.stem + ".clean.mkv")
    log = (Path(a.log_dir) if a.log_dir else HERE / "log") / (src.stem + ".profmute.txt")
    if out.suffix.lower() != ".mkv":
        sys.exit(f"the output file must end in .mkv: {out}")
    if out.resolve() == src.resolve():
        sys.exit("the output file is the movie itself; pick a different name so the original stays untouched")
    out_srt = Path(a.out_srt) if a.out_srt else out.with_name(out.stem + ".en.srt")
    if out_srt.suffix.lower() != ".srt":
        sys.exit(f"the clean subtitle file must end in .srt: {out_srt}")
    if a.srt and out_srt.resolve() == Path(a.srt).resolve():
        sys.exit("the clean subtitle file is the subtitle file being read; pick a different name")
    rules = use_words(a.words)
    model_name = a.model or load_models()[0][0]
    need_ffmpeg()
    log.parent.mkdir(parents=True, exist_ok=True)
    if not a.dry:
        out.parent.mkdir(parents=True, exist_ok=True)

    # with --review-file: analyse only, and save the questions for later; with --from-review: write, with the answers
    later = bool(a.review_file) and not a.dry
    settings = analysis_settings(a, src, rules, model_name)
    if later and review_is_current(a.review_file, settings):
        print("Already analysed in an earlier batch: using that, and any answers you gave.")
        return
    picked_lines, picks = [], {}
    if a.from_review:
        state, model = load_review(a.from_review, src), None
        hits, conflict_lines, decided = review_mutes(state)
        picks = state.get("picks") or {}
        hits, picked_lines = apply_picks(hits, picks, a.speak and not a.no_separate)
        if state["questions"]:
            state["decided"] = decided
        state.update(hits=hits, conflict_lines=conflict_lines)
    else:
        clips = None
        if later:
            clips = review_clips(a.review_file)
            shutil.rmtree(clips, ignore_errors=True)
            Path(clips).mkdir(parents=True, exist_ok=True)
        state, model = analyse(a, src, out, out_srt, model_name, rules, later, clips)
        if later:
            save_review(a.review_file, dict(state, settings=settings, movie=movie_identity(src),
                                            answers={"conflicts": {}, "unresolved": {}}))
            asks = len(state["pending"]) + len(state["questions"])
            print(f"Analysed: {len(state['hits'])} spot(s) to mute so far, {asks} question(s) saved for later.")
            return
    words, cues, notes = state["words"], [tuple(c) for c in state["cues"]], state["notes"]
    usable_cues = cues if state["usable"] else []
    hits, conflict_lines, unresolved = [tuple(h) for h in state["hits"]], state["conflict_lines"], state["unresolved"]
    decided = {int(k): v for k, v in state["decided"].items()}
    out_srt, model_name = Path(state["out_srt"]), state["model"]
    unresolved_lines = [f"{stamp(cs)}  {label}  <-  {flat(cues[k][2])}" + (f"  ->  {decided[n]}" if n in decided else "")
                        for n, (cs, _, label, k) in enumerate(unresolved)]

    # pad and merge overlaps
    spans = sorted((max(0.0, s - a.pad_before), e + a.pad_after, w, tag) for s, e, w, tag in hits)
    notes.append(f"Padding: {a.pad_before:.2f}s before each word, {a.pad_after:.2f}s after.")
    merged = []
    for s, e, w, tag in spans:
        if merged and s <= merged[-1][1]:
            m = merged[-1]
            merged[-1] = (m[0], max(e, m[1]), m[2] if w == m[2] else m[2] + " " + w, m[3] or tag)
        else:
            merged.append((s, e, w, tag))

    # some surround mixes put a little dialogue in the front left/right too: listen there for each word
    also_front = set()
    if merged and not a.all_channels and not a.no_front_check:
        names = track_info(src, a.audio_index)[2]
        if names and "FC" in names and len(names) > 2:
            if model is None:     # writing from a saved analysis: Whisper is needed again for this
                model = load_model(model_name, a.device)[0]
            also_front = front_heard(model, src, a.audio_index, merged, names)
            print(f"    {len(also_front)} word(s) also heard in the front left/right speakers; changed there too.")
            notes.append(f"Front left/right check: the word was heard there too at {len(also_front)} of {len(merged)} spots.")
            merged = [(s, e, w, ", ".join(filter(None, [tag, "also front left/right"])) if i in also_front else tag)
                      for i, (s, e, w, tag) in enumerate(merged)]

    # subtitles with the same words deleted, written next to the clean copy once that exists
    srt_text = None
    # your words from the transcript go in the subtitles only where they were said (below); until then, deleted
    said_only = lambda done: dict(picks, mute=[m[:3] + [m[3]] if len(m) > 3 and m[3] and any(h[0] < m[1] and m[0] < h[1] for h in done)
                                               else m[:3] for m in picks.get("mute", [])])
    if cues and merged and not a.dry:
        srt_text, deleted, dropped = clean_srt(cues, picks=said_only([]))
        notes.append(f"Clean subtitles: {out_srt} ({deleted} word(s) deleted, {dropped} line(s) dropped as empty).")

    with open(log, "w", encoding="utf-8") as f:
        for s, e, w, tag in merged:
            f.write(f"{stamp(s)}  {e - s:.2f}s  {w}" + (f"  [{tag}]" if tag else "") + "\n")
        if conflict_lines:
            f.write("\nCONFLICTS - heard by Whisper, not in the subtitles:\n" + "\n".join(conflict_lines) + "\n")
        if unresolved:
            f.write("\nUNRESOLVED - in the subtitles but not heard in the audio. "
                    + ("Not muted unless the line says so; check by ear:\n" if decided else "NOT muted, check by ear:\n")
                    + "\n".join(unresolved_lines) + "\n")
        if picked_lines:
            f.write("\nTRANSCRIPT - your changes in the transcript review:\n" + "\n".join(picked_lines) + "\n")
        f.write("\n" + "\n".join(notes) + "\n")
    print(f"Found {len(merged)} spots to mute. Log: {log}")
    if picked_lines:
        print(f"    {len(picked_lines)} change(s) from your transcript review.")
    for line in conflict_lines:
        print(f"    CONFLICT   {line}")
    for line in unresolved_lines:
        print(f"    UNRESOLVED {line}")
    if a.dry or not merged:
        if a.from_review and not a.dry:
            drop_review(a.from_review)
        return

    print("4/4 Writing clean copy (video copied, only the audio is re-encoded)...")
    voice, trouble, speaking = None, None, None
    if a.speak:
        import torch
        if a.no_separate:
            trouble = "Speaking a clean word needs the voice removal; the words were muted instead."
        elif not torch.cuda.is_available():
            trouble = "Speaking a clean word needs an NVIDIA graphics card; the words were muted instead."
        if trouble:
            print("    " + trouble)
    if not a.no_separate:
        del model                     # Whisper is done: make room on the graphics card for the voice model
        gc.collect()
        if a.speak and not trouble:
            import speak
            span_of = lambda s, e: next(i for i, m in enumerate(merged) if m[0] <= s + 1e-6 and e <= m[1] + 1e-6)
            sentences = speak.plan_sentences([(s, e, w, span_of(s, e)) for s, e, w, tag in hits if tag != PICKED],
                                             words, usable_cues)   # a word you only muted in the transcript stays muted
            # chosen before: Gemma's while listening, yours in the transcript review (only the rest are asked now)
            chosen = [(s, e, w, by) for s, e, _, w, by in state.get("say", [])] +                      [(s, e, w, "you") for s, e, _, w in picks.get("say", [])] +                      [(m[0], m[1], m[3], "you") for m in picks.get("mute", []) if len(m) > 3 and m[3]]
            try:   # Gemma has the graphics card to itself here, between Whisper and the voice model
                speak.choose_words(sentences, sys.modules[__name__], chosen)
                speaking = dict(sentences=sentences, words=words, model=model_name, device=a.device)
            except Exception as e:
                trouble = f"The clean words could not be chosen ({first_line(e)}); the words were muted instead."
                print("    " + trouble)
        name = a.voice_model or load_voice_models()[0][0]
        try:
            print(f"    Loading the voice model {name} (its first use downloads it)...")
            voice = VoiceRemover(name)
        except Exception as e:
            trouble = f"The voice model {name} could not be used ({(str(e).strip().splitlines() or [type(e).__name__])[0][:200]}); " \
                      f"the words were silenced instead."
            print("    " + trouble)
    how = write_clean_audio(src, out, a.audio_index, [m[:2] for m in merged], not a.no_fade, not a.all_channels,
                            also_front, voice, speaking)
    print("    " + how)
    spoken_lines = []
    if speaking:
        if speaking.get("trouble"):
            trouble = " ".join(filter(None, [trouble, speaking["trouble"]]))
        import speak
        said = 0
        for s in speaking["sentences"]:
            result = s.get("result") or ("muted: " + s["muted"] if s["muted"] else "muted")
            said += result.startswith("spoken")
            line = speak.marked(s, s.get("picks")) if result.startswith("spoken") else speak.marked(s)
            yours = " (your word)" if result.startswith("spoken") and "you" in (s.get("chosen_by") or []) else ""
            spoken_lines.append(f"{stamp(s['hit'][0][0])}  {result}{yours}  |  {line}")
        how += f" Spoken clean words: {said} of {len(speaking['sentences'])} sentence(s); the rest stay muted."
        print(f"    Spoke the clean word(s) in {said} of {len(speaking['sentences'])} sentence(s).")
        if srt_text is not None and usable_cues:     # the subtitles say the clean word too, where it was spoken
            done = [(s["hit"][j], " ".join(w[2] for w in s["words"][f:l + 1]), s["picks"][j]) for s in speaking["sentences"]
                    if (s.get("result") or "").startswith("spoken") for j, (f, l) in enumerate(s["swears"])]
            yours = [m for m in picks.get("mute", []) if len(m) > 3 and m[3]]
            swapped = spoken_in_cues(usable_cues, [(h[0], swear, clean) for h, swear, clean in done      # swears; your
                                                   if not any(h[0] < m[1] and m[0] < h[1] for m in yours)])  # words: below
            srt_text = clean_srt(usable_cues, swapped, said_only([h for h, _, _ in done]))[0]
            how += f" Clean subtitles: {len(swapped)} spoken word(s) written in place of the swear."
    with open(log, "a", encoding="utf-8") as f:
        f.write((trouble + "\n" if trouble else "") + how + "\n")
        if spoken_lines:
            f.write("\nSPOKEN - the clean word said in the actor's voice, or why the word stayed muted:\n"
                    + "\n".join(spoken_lines) + "\n")
    print("Done:", out)
    if srt_text is None:
        print("No subtitles to clean, so no clean subtitle file was written.")
    else:
        out_srt.parent.mkdir(parents=True, exist_ok=True)
        out_srt.write_text(srt_text, encoding="utf-8")
        print("Clean subtitles:", out_srt)
    if a.from_review:
        drop_review(a.from_review)


if __name__ == "__main__":
    main()
