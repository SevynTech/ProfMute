"""profmute - mute profanity in a video's main audio track.

Usage:  uv run python profmute.py "C:\\path\\movie.mkv" [--dry] [--srt subs.srt | --no-srt] [--model large-v3]
                                 [--out clean.mkv] [--out-srt clean.srt] [--log-dir folder] [--words words.txt]
                                 [--pad-before 0.02] [--pad-after 0.30] [--device auto|cuda|cpu]
                                 [--confirm] [--conflicts ask|auto]
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
import argparse, bisect, json, os, re, shutil, subprocess, sys, tempfile
from collections import Counter
from pathlib import Path

__version__ = "1.0.0"
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

[phrases]
# Several words on a line: muted from the first word to the last, when said together.
son of a bitch*
sons of bitches
god damn*
jesus christ
mother fuck*

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

MAX_GAP = 1.0  # seconds; phrase words further apart than this are not treated as a phrase

# ---- EDIT HERE: seconds of extra silence around each word (also --pad-before / --pad-after) ----
# Whisper tends to mark a word's start about right and its end too early, so most of the padding goes after.
PAD_BEFORE = 0.02
PAD_AFTER = 0.30

SR = 16000           # sample rate Whisper wants
SRT_TOL = 1.5        # seconds; a subtitle hit counts as heard if Whisper has a hit this close to the line
RESCAN_PAD = 2.0     # seconds of audio added on each side of a subtitle line when re-listening
OFFSET_SEARCH = 30.0 # seconds; how far out of sync a subtitle file may be and still get lined up
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
        print(r.stderr[-2000:])
        sys.exit("command failed: " + " ".join(Path(cmd[0]).name if i == 0 else c for i, c in enumerate(cmd[:3])))
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


def stamp(t):
    t = round(t, 2)
    return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def norm(word):
    """(raw, tok): lowercased with the outer punctuation stripped, and the letters only."""
    raw = word.lower().strip(STRIP)
    return raw, re.sub(r"[^a-z]", "", raw)


# ---------------------------------------------------------------- word list

class WordListError(ValueError):
    pass


class Rules:
    """A loaded word list. words/censored/cutoff are single regexes, phrases a list of regex lists."""
    def __init__(self, words, phrases, censored, cutoff, source):
        star = lambda entry: "[a-z]*".join(re.escape(part) for part in entry.split("*"))
        either = lambda patterns: re.compile("|".join(f"(?:{p})" for p in patterns) or "(?!)")
        self.words = either(star(w) for w in words)
        self.phrases = [[re.compile(star(w)) for w in phrase] for phrase in phrases]
        self.censored = either(censored)
        self.cutoff = either(re.escape(c) for c in cutoff)
        self.source = source
        self.summary = f"{len(words)} words, {len(phrases)} phrases"


def parse_words(text, source):
    """Read a word list (see DEFAULT_WORDS for the format). Raises WordListError naming every bad line."""
    sections = {"words": "words", "word": "words", "phrases": "words", "phrase": "words",
                "censored": "censored", "cutoff": "cutoff"}
    section, words, phrases, censored, cutoff, problems = "words", [], [], [], [], []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        header = re.fullmatch(r"\[(.+)\]", line)
        if header:
            section = sections.get(re.sub(r"[^a-z]", "", header.group(1).lower()))
            if section is None:
                problems.append(f"line {n}: unknown section {line} (use [words], [phrases], [censored] or [cut-off])")
            continue
        if section is None:
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
    if problems:
        raise WordListError("\n".join(problems))
    return Rules(words, phrases, censored, cutoff, source)


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


def match_len(toks, i, gap_ok=None):
    """How many tokens starting at i make up one profanity hit (0 = none). toks = [(raw, tok), ...]"""
    for ph in RULES.phrases:
        n = len(ph)
        chunk = toks[i:i + n]
        if len(chunk) == n and all(p.fullmatch(c[1]) for p, c in zip(ph, chunk)) \
           and (gap_ok is None or all(gap_ok(i + k) for k in range(n - 1))):
            return n
    raw, tok = toks[i]
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
    first_line = lambda e: (str(e).strip().splitlines() or [type(e).__name__])[0][:300]
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


def clean_cue(text):
    """One subtitle cue with its profanity deleted. -> (new text, '' if nothing is left; words deleted)

    The words are simply removed. A deleted word hands its sentence-ending punctuation to the word
    before it ("Oh, shit." -> "Oh."), and the next word is capitalized when the sentence now starts
    there ("Damn it." -> "It."). Lines and cues with no words left are dropped.
    """
    pieces, hits = cue_scan(text)
    if not hits:
        return text, 0
    drop = {i + k for i, n, _ in hits for k in range(n)}
    kept = []                # [line number, lead tags, body, trail tags] of the words that stay
    carry, capitalize = "", False   # tags/quotes owed to the next kept word; capitalize it?
    for i, (line, piece) in enumerate(pieces):
        lead, body, trail = SPLIT_TAGS.match(piece).groups()
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
    return "\n".join(out), len(hits)


def clean_srt(cues):
    """-> (text of a subtitle file with the profanity deleted, words deleted, cues dropped as empty)"""
    def t(x):
        ms = max(0, round(x * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    blocks, deleted, dropped = [], 0, 0
    for cs, ce, text in cues:
        new, n = clean_cue(text)
        deleted += n
        if new:
            blocks.append(f"{len(blocks) + 1}\n{t(cs)} --> {t(ce)}\n{new}\n")
        else:
            dropped += 1
    return "\n".join(blocks), deleted, dropped


def estimate_offset(cues, words):
    """Guess how far the subtitles are shifted from the audio.

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
        lo = bisect.bisect_left(starts, cs - OFFSET_SEARCH)
        hi = bisect.bisect_right(starts, cs + OFFSET_SEARCH)
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
    """Put one conflict to the user. -> 'mute', 'leave', or 'auto' (three listens decide this and the rest)"""
    if sys.stdin is not None and sys.stdin.isatty():
        print(f"\nCONFLICT {info['n']} of {info['of']} at {info['time']}: Whisper heard \"{info['word']}\", "
              f"the subtitles do not have it.")
        print(f"    Whisper:   {info['before']} >>{info['word']}<< {info['after']}")
        print(f"    Subtitles: {info['subtitles'] or '(nothing at that moment)'}")
        while True:
            answer = input("    [m]ute it, [l]eave it, or let three listens decide this and the [r]est? ").strip().lower()[:1]
            if answer in ("m", "l", "r"):
                return {"m": "mute", "l": "leave", "r": "auto"}[answer]
    print(ASK + json.dumps(info), flush=True)
    answer = sys.stdin.readline().strip() if sys.stdin is not None else ""
    return answer if answer in ("mute", "leave") else "auto"


def settle(model, samples, hits, words, cues, backed, confirm, conflicts, dry):
    """Decide what is muted: optional second listens for every hit, then the conflicts.

    hits    = [(start, end, text, tag), ...] sorted by time
    backed  = indexes of the hits the subtitles back up, or None when no subtitles are in use
    -> (hits to mute, conflict lines for the log, Counter of what happened)
    """
    import numpy as np
    is_conflict = lambda i: backed is not None and i not in backed
    asking = conflicts == "ask" and not dry
    votes, stats, mute, report = {}, Counter(), [], []   # stats: how many votes ended confirmed/moved/unsure

    def get_vote(i):
        if i not in votes:
            votes[i] = vote(model, samples, hits[i], hits[:i] + hits[i + 1:])
        return votes[i]

    need = [i for i in range(len(hits)) if confirm or (is_conflict(i) and conflicts == "auto")]
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
        if asking:
            near = [w for w in words if s - 4 <= w[0] <= e + 4]
            before = " ".join(w[2] for w in near if w[1] <= s + 0.01)
            after = " ".join(w[2] for w in near if w[0] >= e - 0.01)
            info = {"n": todo.index(i) + 1, "of": len(todo), "time": stamp(where[0]), "word": text,
                    "before": before if len(before) <= 80 else "... " + before[-80:].partition(" ")[2],
                    "after": after if len(after) <= 80 else after[:80].rpartition(" ")[0] + " ...",
                    "subtitles": "  /  ".join(flat(c[2]) for c in cues if c[0] < e + 3 and c[1] > s - 3),
                    "listens": f"heard in {heard} listens" if heard else None, "clip": None}
            if sys.stdin is None or not sys.stdin.isatty():  # the window can play it: a few seconds around the word
                clips = clips or tempfile.mkdtemp(prefix="profmute-")
                info["clip"] = os.path.join(clips, f"conflict{info['n']}.wav")
                import wave
                with wave.open(info["clip"], "wb") as wf:
                    wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(SR)
                    part = samples[max(0, int((where[0] - 3) * SR)):int((where[1] + 3) * SR)]
                    wf.writeframes((np.clip(part, -1, 1) * 32767).astype(np.int16).tobytes())
            answer = ask_user(info)
            if answer == "auto":
                asking = False
        if answer == "mute":
            mute.append((where[0], where[1], text, "conflict: you chose to mute"))
            report.append(line + "  ->  muted (your choice)")
        elif answer == "leave":
            report.append(line + "  ->  left in (your choice)")
        else:
            verdict, spans, heard = get_vote(i)
            if verdict == "unsure":
                times, of = heard.split(" of ")
                why = "heard in a different place on every listen" if times == of else \
                      f"heard in {heard} listens, but never twice in the same place" if int(times) > 1 else \
                      f"heard in only {heard} listens"
                report.append(f"{stamp(s)}  {text}  ->  left in ({why})")
            else:
                mute += [(a, b, text, f"conflict: heard in {heard} listens") for a, b in spans]
                report.append(f"{stamp(spans[0][0])}  {text}  ->  muted (heard in {heard} listens)")
        stats["conflict"] += 1
    if clips:
        shutil.rmtree(clips, ignore_errors=True)
    stats.update(v[0] for v in votes.values())
    return sorted(mute), report, stats


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
    ap.add_argument("--confirm", action="store_true", help="listen to every word a second time to check where it is")
    ap.add_argument("--conflicts", choices=("ask", "auto"), default="auto",
                    help="a word the subtitles do not have: ask = you decide, auto = three listens decide")
    ap.add_argument("--list-models", action="store_true", help="print the models of models.txt as JSON and exit")
    ap.add_argument("--version", action="version", version=f"ProfMute {__version__}")
    a = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")
    if a.list_models:
        return print(json.dumps(list_models()))
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

    print("1/4 Extracting audio...")
    samples = load_audio(src, a.audio_index)
    cues, srt_name = [], None
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
        if agree is not None and agree < MIN_AGREEMENT:
            print(f"    These subtitles do not line up with the audio (only {agree:.0%} of lines agree). Ignoring them.")
            notes.append(f"Subtitles: {srt_name} does NOT match this audio, ignored. Whisper only.")
        else:
            if abs(offset) < 0.5:
                offset = 0.0
            else:
                print(f"    Subtitles are {abs(offset):.1f}s {'early' if offset > 0 else 'late'}, shifting them to match.")
                cues = [(cs + offset, ce + offset, text) for cs, ce, text in cues]
            before = len(hits)
            hits, unresolved, relistened = subtitle_pass(model, samples, cues, hits,
                                                         lambda: load_audio(src, a.audio_index, VOICE_BAND))
            backed = match_subs(subtitle_hits(cues), hits)[1]
            print(f"    {relistened} line(s) re-listened to, {len(hits) - before} more hit(s) found, "
                  f"{len(unresolved)} unresolved.")
            sync = f"shifted {offset:+.1f}s" if offset else "in sync"
            notes.append(f"Subtitles: {srt_name}, {sync}. {relistened} line(s) re-listened to, "
                         f"{len(hits) - before} more hit(s) found, {len(unresolved)} unresolved.")

    hits, conflict_lines, stats = settle(model, samples, hits, words, cues, backed, a.confirm, a.conflicts, a.dry)
    if a.confirm:
        print(f"    Second listens: {stats['confirmed']} confirmed, {stats['moved']} moved, {stats['unsure']} uncertain.")
        notes.append(f"Second listens: {stats['confirmed']} confirmed, {stats['moved']} moved, "
                     f"{stats['unsure']} uncertain.")
    if conflict_lines:
        print(f"    {len(conflict_lines)} conflict(s): heard by Whisper, not in the subtitles.")

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

    # subtitles with the same words deleted, written next to the clean copy once that exists
    srt_text = None
    if cues and merged and not a.dry:
        srt_text, deleted, dropped = clean_srt(cues)
        notes.append(f"Clean subtitles: {out_srt} ({deleted} word(s) deleted, {dropped} line(s) dropped as empty).")

    with open(log, "w", encoding="utf-8") as f:
        for s, e, w, tag in merged:
            f.write(f"{stamp(s)}  {e - s:.2f}s  {w}" + (f"  [{tag}]" if tag else "") + "\n")
        if conflict_lines:
            f.write("\nCONFLICTS - heard by Whisper, not in the subtitles:\n" + "\n".join(conflict_lines) + "\n")
        if unresolved:
            f.write("\nUNRESOLVED - in the subtitles but not heard in the audio. NOT muted, check by ear:\n")
            for cs, _, label, k in unresolved:
                f.write(f"{stamp(cs)}  {label}  <-  {flat(cues[k][2])}\n")
        f.write("\n" + "\n".join(notes) + "\n")
    print(f"Found {len(merged)} spots to mute. Log: {log}")
    for line in conflict_lines:
        print(f"    CONFLICT   {line}")
    for cs, _, label, k in unresolved:
        print(f"    UNRESOLVED {stamp(cs)}  {label}  <-  {flat(cues[k][2])}")
    if a.dry or not merged:
        return

    expr = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e, *_ in merged)
    flt = f"volume=enable='{expr}':volume=0"
    print("4/4 Writing clean copy (video copied, only the audio is re-encoded)...")
    run([FFMPEG, "-y", "-i", str(src), "-map", "0", "-c", "copy",
         f"-filter:a:{a.audio_index}", flt,
         f"-c:a:{a.audio_index}", "aac", f"-b:a:{a.audio_index}", "384k", str(out)])
    print("Done:", out)
    if srt_text is None:
        print("No subtitles to clean, so no clean subtitle file was written.")
    else:
        out_srt.parent.mkdir(parents=True, exist_ok=True)
        out_srt.write_text(srt_text, encoding="utf-8")
        print("Clean subtitles:", out_srt)


if __name__ == "__main__":
    main()
