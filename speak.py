"""speak.py - say a clean word in the actor's own voice instead of muting a swear (ProfMute's --speak option).

Used by profmute.py; the work happens in three steps, each with the graphics card to itself:

1. plan_sentences()  which swears to speak: each one's sentence comes from Whisper's word timings (bounded by
                     the subtitle line when there is one). Shouts get a clean word too, said in a normal voice.
2. choose_words()    Gemma 4 12B, run by llama.cpp's server, rewrites each sentence with clean words, following
                     the style rules and examples below; words set in the word list's [replacements] always win.
3. speak()           inside the audio writer, on the movie's own samples: the voice model separates each
                     sentence's voice; dots.tts.edit says the sentence again with the clean words; Whisper checks
                     it, and the clean word's pitch (dots.tts copies a scream's delivery, badly: a yelled word is
                     tried again calmer); three tries, otherwise the spot stays muted; wav2vec2 finds word edges;
                     the new words are cut in at the quiet points around the swear, over the voice-free sound.

The models download themselves into the "speak-models" folder the first time they are needed.
Everything here receives the running profmute module as `pm` (its word list and helpers).
"""
import json, re, shutil, socket, subprocess, sys, tempfile, time, urllib.request, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODELS = HERE / "speak-models"
LLAMA_BUILD = "b11312"                       # llama.cpp, Windows CUDA 12.4 build (1 October 2026)
LLAMA_URLS = [f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_BUILD}/llama-{LLAMA_BUILD}-bin-win-cuda-12.4-x64.zip",
              f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_BUILD}/cudart-llama-bin-win-cuda-12.4-x64.zip"]
GEMMA = ("google/gemma-4-12B-it-qat-q4_0-gguf", "gemma-4-12b-it-qat-q4_0.gguf")
DOTS = "dots-studio/dots.tts.edit"
YELL_HZ = 300           # a clean word dots.tts says this high is a yell: tried again calmer, else muted. It copies
YELL_DB = -18           # a scream's delivery, badly. With no pitch at all, it is a yell only this loud (peak dB);
                        # quieter, it is a whisper or a gravelly voice. Both set on the spots judged by ear.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

STYLE = """You make movie dialogue family-friendly by replacing swear words with clean ones, for a version of the
movie in which the actor's own voice says the clean word. The swears to replace are marked with [square brackets].
Rewrite the line with every bracketed swear replaced, and change nothing else.

How to choose, in order of importance:
1. Keep the meaning, the grammar and the word form: fucking -> freaking, fucked -> screwed or messed,
   fuckers -> jerks, assholes -> jerks.
2. Use plain words an actor would really say: heck, crap, dang, darn, jerk, idiot, screw, freaking, mess, butt,
   stupid, stuff, pee, son of a gun. Never made-up or cutesy sound-alikes (no "fudge", "mother trucker",
   "shut the front door"), and no swearing at all, not even damn, hell, ass, bitch or bastard.
3. Pick what fits the sentence:
   - "the fuck" (where/what/who the fuck, shut the fuck up, get the fuck out) -> heck
   - "fuck no", "fuck yes", "fuck yeah" -> heck no, heck yes, heck yeah
   - "fuck you", "fuck it", "fuck your X", "go fuck yourself" -> screw
   - "fuck off" -> buzz off; "fuck up" (to ruin or hurt) -> mess up, beat up
   - "fuck" meaning to have sex (gonna fuck, fucked her) -> make out, hook up
   - "oh my fuck", "oh my god" -> oh my gosh
   - "fucking" before a word -> freaking, or stupid when it is about hurting someone
   - a lone exclamation (Fuck! Shit!) -> Dang! or Crap!
   - "shit" meaning things or stuff -> stuff; meaning nonsense or trouble -> crap
   - an insult (motherfucker, asshole, dick, fucker, douchebag) -> jerk, or a friendlier word like buddy when it is
     affectionate; "son of a bitch" -> son of a gun
   - "goddamn" -> darn or stupid; "damn" -> darn
4. About as long as the original, so it fits the time the actor took.
Answer with the rewritten line only, without brackets, quotes or explanation."""

# worked examples: swears marked, and the clean words chosen for them by hand
EXAMPLES = [
    ("get my country's name out of your [fucking] mouth", ["freaking"]),
    ("now get the [fuck] out of my bar", ["heck"]),
    ("Shutting the [fuck] up is also free.", ["heck"]),
    ("You're a [fucking] joke.", ["freaking"]),
    ("You couldn't even save a relationship with a [goddamn] stripper.", ["lousy"]),
    ("It's like Pinocchio jammed his face in my [ass] and started lying like crazy.", ["butt"]),
    ("i don't give a [shit] about your world", ["crap"]),
    ("And you look [damn] good in that suit.", ["darn"]),
    ("[Fuck]!", ["Dang"]),
    ("Merchant who didn't order the [fucking] pie.", ["freaking"]),
    ("I'm just a bad guy who gets paid to [fuck] up worse guys.", ["mess"]),
    ("I'll send your shiny happy [ass] a friend request.", ["butt"]),
    ("Hey, don't take any [shit] from him, Cunningham.", ["crap"]),
    ("[Motherfucker]!", ["Son of a gun"]),
    ("[Shit]!", ["Dang"]),
    ("then the hairy [motherfucker] ups the ante by dying", ["son of a gun"]),
    ("I used to live in a [shithole] just like it", ["dump"]),
    ("And how would I do that exactly, because where the [fuck] is everyone?", ["heck"]),
    ("you are not judge jury or executioner [fuck] your rules", ["screw"]),
    ("Oh, you call me [motherfucker]!", ["son of a gun"]),
    ("Holy [shit], Pickles.", ["crap"]),
    ("We are so [fucked].", ["screwed"]),
    ("[Fuck] no, I'm not going back in there.", ["Heck"]),
    ("[Fuck] yeah, let's do this!", ["Heck"]),
    ("Then whose kitty litter did I just [shit] in?", ["poop"]),
    ("Think of us as really [fucked] up tooth fairies.", ["messed"]),
    ("Trust me, that wheezing bag of [dick]-tips has it coming.", ["jerk"]),
    ("I think we can all agree that [shit] just went sideways.", ["stuff"]),
    ("Oh, and I thought you guys were [dicks] before.", ["jerks"]),
    ("This [shit]'s gonna have nuts in it.", ["stuff"]),
    ("I've been trying to tell you [assholes],", ["idiots"]),
    ("Tell Beast to stop [shitting] on my lawn.", ["pooping"]),
    ("Either that or slap the [bitch] outta you!", ["sass"]),
    ("Cheers. To your health. [Fuck] you.", ["Screw"]),
    ("You ever hear of the one-legged man in the [ass]-kicking contest?", ["butt"]),
    ("Are you two gonna [fuck] or fight?", ["kiss"]),
    ("Some [motherfucker] still trying to ice skate up here.", ["jerk"]),
    ("It's like an armadillo [fucked] a gremlin.", ["had a baby with"]),
    ("Make those TVA [fuckers] fix my [shit].", ["jerks", "stuff"]),
]
# when the model's answer cannot be used twice over: a plain word by the swear's stem
DEFAULTS = [("motherfuck", "jerk"), ("fucking", "freaking"), ("fucked", "messed"), ("fucker", "jerk"), ("fuck", "heck"),
            ("shitting", "messing"), ("shithole", "dump"), ("shit", "crap"), ("asshole", "jerk"), ("ass", "butt"),
            ("bitch", "jerk"), ("goddam", "darn"), ("damn", "darn"), ("dick", "jerk"), ("piss", "pee"), ("cock", "jerk"),
            ("douche", "jerk"), ("bastard", "jerk")]
FILLER = {"is", "a", "an", "the", "and", "or", "of", "to", "it", "i", "in", "on", "at", "be", "was", "are", "that",
          "this", "so", "but", "with", "for", "as", "s", ""}


def say(text):
    print("    " + text, flush=True)


def letters(word):
    return re.sub(r"[^a-z']", "", word.lower())


# ------------------------------------------------------------------ 1. which swears, in which sentences

def plan_sentences(hits, words, cues):
    """hits = [(start, end, text, span index), ...]; words = Whisper's [(start, end, text, raw, tok), ...];
    cues = subtitles [(start, end, text)] on the movie's clock.
    -> [{"words": [(start, end, text)], "swears": [(first, last) word indexes], "spans": [span index per swear],
         "hit": [(start, end) per swear], "muted": reason or None}, ...]
    Shouts are spoken too, in a normal voice: no measure told them apart from gruff speech, and a calm clean
    word over a shout sounds better than a muted gap."""
    ranges, lost = [], []                 # per hit: (first sentence word, last sentence word, first swear word, last)
    for hs, he, text, span in hits:
        over = [i for i, w in enumerate(words) if w[1] > hs and w[0] < he]
        if not over:
            lost.append(dict(words=[], swears=[], spans=[[span]], hit=[(hs, he)], muted="not in Whisper's transcript"))
            continue
        first, last = over[0], over[-1]
        a = first
        while a > 0 and words[a][0] - words[a - 1][1] < 0.8 and hs - words[a - 1][0] < 8:
            a -= 1
        b = last
        while b < len(words) - 1 and words[b + 1][0] - words[b][1] < 0.8 and words[b + 1][1] - he < 4:
            b += 1
        # the sentence: by the subtitle line's text when one fits (machine-made subtitle times are loose)
        bounded = False
        near = [c for c in cues if c[0] - 3 <= hs <= c[1] + 3 and any(letters(words[i][2]).strip("'") in letters(c[2]) for i in over)]
        if near:
            cue = min(near, key=lambda c: abs((c[0] + c[1]) / 2 - hs))
            cw = cue[2].split()
            k = next((j for j, x in enumerate(cw) if letters(words[first][2]) and letters(words[first][2]) in letters(x)), None)
            if k is not None:
                stop = lambda x: x.rstrip('"\')').endswith((".", "?", "!"))
                k0 = k
                while k0 > 0 and not stop(cw[k0 - 1]):
                    k0 -= 1
                k1 = k
                while k1 < len(cw) - 1 and not stop(cw[k1]):
                    k1 += 1
                a, b = max(a, first - (k - k0)), min(b, last + (k1 - k))
                bounded = True
        if not bounded:
            while a < first and words[a][0] < hs - 3.0:
                a += 1
            while b > last and words[b][1] > he + 2.0:
                b -= 1
        ends = lambda w: w[2].rstrip('"\')').endswith((".", "?", "!"))
        while a < first and any(ends(w) for w in words[a:first]):
            a += 1
        while b > last and any(ends(w) for w in words[first:b]):
            b -= 1
        ranges.append((a, b, first, last, span, (hs, he)))
    # swears whose sentences overlap share one sentence (and one edit)
    ranges.sort()
    groups = []
    for r in ranges:
        if groups and r[0] <= groups[-1][-1][1]:
            groups[-1].append(r)
        else:
            groups.append([r])
    out = list(lost)
    for g in groups:
        a, b = min(r[0] for r in g), max(r[1] for r in g)
        g.sort(key=lambda r: r[2])
        # swears that touch ("shit-fucks", "son of a bitch" heard as two hits) become one, so the clean words
        # chosen for them cannot be split in the wrong place
        swears, spans_of, hit = [], [], []
        for r in g:
            f, l = r[2] - a, r[3] - a
            if swears and f <= swears[-1][1] + 1:
                swears[-1] = (swears[-1][0], max(l, swears[-1][1]))
                spans_of[-1].append(r[4])
                hit[-1] = (min(hit[-1][0], r[5][0]), max(hit[-1][1], r[5][1]))
            else:
                swears.append((f, l))
                spans_of.append([r[4]])
                hit.append(r[5])
        out.append(dict(words=[tuple(w[:3]) for w in words[a:b + 1]], swears=swears, spans=spans_of, hit=hit, muted=None))
    return sorted(out, key=lambda s: s["hit"][0][0])


def marked(s, picks=None):
    """The sentence with its swears in [brackets], or (with picks) with them replaced."""
    parts, i = [], 0
    for j, (f, l) in enumerate(s["swears"]):
        parts += [w[2] for w in s["words"][i:f]]
        swear = " ".join(w[2] for w in s["words"][f:l + 1])
        core = re.sub(r"[^\w']+$", "", swear)
        tail = swear[len(core):]
        lead = re.match(r"^[^\w']*", core).group(0)
        core = core[len(lead):]
        if picks is None:
            parts.append(f"{lead}[{core}]{tail}")
        else:
            pick = picks[j]
            pick = pick[:1].upper() + pick[1:] if core[:1].isupper() else pick
            parts.append(f"{lead}{pick}{tail}")
        i = l + 1
    parts += [w[2] for w in s["words"][i:]]
    return " ".join(parts)


def instruction(s, calm=False):
    """dots.tts's edit instruction: <sub targ="clean">swear</sub> for each swear. calm: without the "!" and the
    SHOUTING CAPS, for another try after the clean word came out shouted."""
    parts, i = [], 0
    for j, (f, l) in enumerate(s["swears"]):
        parts += [w[2] for w in s["words"][i:f]]
        swear = " ".join(w[2] for w in s["words"][f:l + 1])
        core = re.sub(r"[^\w']+$", "", swear)
        lead = re.match(r"^[^\w']*", core).group(0)
        clean = s["picks"][j]
        clean = clean[:1].upper() + clean[1:] if core[len(lead):][:1].isupper() else clean
        parts.append(f'{lead}<sub targ="{clean}">{core[len(lead):]}</sub>{swear[len(core):]}')
        i = l + 1
    parts += [w[2] for w in s["words"][i:]]
    text = " ".join(parts)
    if calm:
        text = "".join(p if p.startswith("<") else re.sub(r"\b[A-Z][A-Z']+\b", lambda m: m[0] if m[0] == "I" else m[0].lower(),
                                                          p.replace("!", "."))
                       for p in re.split(r"(<[^>]+>)", text))
    return text


def _yell(x16, heard, picks):
    """Did dots.tts yell a clean word? Measured on its sentence (16 kHz), each word found by Whisper's timing:
    pitch YELL_HZ or higher, or no pitch at all while loud (a harsh yell; a whisper or a gravelly voice has no pitch
    either, but is quiet). -> (yelled, what was measured, for the log)."""
    import numpy as np, librosa
    said = [letters(w[2]).strip("'") for w in heard]
    yelled, notes = False, []
    for p in picks:
        want = [letters(w).strip("'") for w in p.split()]
        i = next((i for i in range(len(said) - len(want) + 1) if said[i:i + len(want)] == want), None)
        if i is None:
            continue
        seg = x16[int(heard[i][0] * 16000):int(heard[i + len(want) - 1][1] * 16000)]
        if len(seg) < 1600:
            continue
        f0, _, _ = librosa.pyin(seg, fmin=70, fmax=800, sr=16000, frame_length=1024, hop_length=160)
        f = f0[~np.isnan(f0)]
        peak = float(20 * np.log10(np.percentile(np.abs(seg), 99) + 1e-9))
        if len(f):
            hz = float(np.median(f))
            yelled |= hz >= YELL_HZ
            notes.append(f"{hz:.0f} Hz")
        else:
            yelled |= peak >= YELL_DB
            notes.append(f"no pitch, {peak:.0f} dB")
    return yelled, "; ".join(notes)


# ------------------------------------------------------------------ 2. choosing the clean words

PM = None   # the running profmute module, set by choose_words() and speak()


def llama_server():
    exe = MODELS / "llama" / "llama-server.exe"
    if not exe.is_file():
        (MODELS / "llama").mkdir(parents=True, exist_ok=True)
        say("Downloading llama.cpp, the engine that runs the word-choosing model (first use only)...")
        for url in LLAMA_URLS:
            z = MODELS / "llama" / url.rsplit("/", 1)[1]
            PM.fetch(url, z, z.name)
            with zipfile.ZipFile(z) as f:
                f.extractall(MODELS / "llama")
            z.unlink()
    return exe


def gemma_file():
    target = MODELS / "gemma" / GEMMA[1]
    if not target.is_file():
        from huggingface_hub import hf_hub_download
        say("Downloading Gemma 4 12B, which chooses the clean words (7 GB, first use only)...")
        hf_hub_download(GEMMA[0], GEMMA[1], local_dir=str(MODELS / "gemma"))
    return target


class Chooser:
    """Gemma 4 behind llama.cpp's OpenAI-style server, for the time of a `with` block."""

    def __enter__(self):
        exe, model = llama_server(), gemma_file()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.proc = subprocess.Popen([str(exe), "-m", str(model), "-ngl", "99", "-c", "8192", "--port", str(self.port),
                                      "--jinja", "--log-disable"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=NO_WINDOW)
        for _ in range(600):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=2) as r:
                    if json.loads(r.read()).get("status") == "ok":
                        return self
            except Exception:
                if self.proc.poll() is not None:
                    raise RuntimeError("the word-choosing model could not be started")
                time.sleep(1)
        raise RuntimeError("the word-choosing model did not start in time")

    def __exit__(self, *_):
        self.proc.kill()
        self.proc.wait()

    def rewrite(self, line, nudge=""):
        messages = [{"role": "system", "content": STYLE}]
        for q, picks in EXAMPLES:
            parts = re.split(r"\[[^\]]+\]", q)
            messages += [{"role": "user", "content": q},
                         {"role": "assistant", "content": parts[0] + "".join(p + rest for p, rest in zip(picks, parts[1:]))}]
        messages.append({"role": "user", "content": line + nudge})
        body = {"messages": messages, "temperature": 0, "max_tokens": 160,
                "chat_template_kwargs": {"enable_thinking": False},
                "logit_bias": [["<|channel>", False]]}    # Gemma 4 can get stuck opening empty "thought" blocks
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            text = (json.loads(r.read())["choices"][0]["message"].get("content") or "").strip()
        return text.splitlines()[0].strip().strip('"') if text else ""


def extract(line, rewritten):
    """The replacements, in order: what stands where each [swear] was, the rest of the line unchanged (compared by
    letters and digits). None when the model changed anything else."""
    pieces = re.split(r"\[[^\]]+\]", line)
    keep = [(i, ch.lower()) for i, ch in enumerate(rewritten) if ch.isalnum()]
    flat = "".join(c for _, c in keep)
    norm = lambda s: "".join(ch.lower() for ch in s if ch.isalnum())
    m = re.match("^" + "(.+?)".join(re.escape(norm(p)) for p in pieces) + "$", flat)
    if not m or not m.lastindex:
        return None
    return [rewritten[keep[m.start(g)][0]:keep[m.end(g) - 1][0] + 1] for g in range(1, m.lastindex + 1)]


def choose_words(sentences, pm):
    """Fill s["picks"] (a clean word or phrase per swear) for every sentence to be spoken."""
    global PM
    PM = pm
    todo = [s for s in sentences if not s["muted"]]
    if not todo:
        return

    def default(swear):
        tok = letters(swear).replace("'", "")
        return next((rep for stem, rep in DEFAULTS if stem in tok), "heck")

    def usable(picks, swears):
        if picks is None or len(picks) != len(swears):
            return False
        for p, sw in zip(picks, swears):
            ws = p.split()
            if not ws or len(ws) > max(4, len(sw.split()) + 2):
                return False
            if all(letters(w).strip("'") in FILLER for w in ws):       # "anal [shit] mary puppets" -> "is": a garbled line
                return False
            if pm.find_hits([(i, i + 0.5, w, *pm.norm(w)) for i, w in enumerate(ws)]):
                return False
        return True

    for s in todo:
        swears = [" ".join(w[2] for w in s["words"][f:l + 1]) for f, l in s["swears"]]
        s["picks"] = [pm.RULES.replacement(sw) for sw in swears]       # the word list's own choices win
        s["chosen_by"] = ["word list" if p else None for p in s["picks"]]
    ask = [s for s in todo if None in s["picks"]]
    if ask:
        say(f"Choosing clean words for {len(ask)} sentence(s) with Gemma 4 12B...")
        with Chooser() as gemma:
            for n, s in enumerate(ask, 1):
                print(f"\r    choosing words {n}/{len(ask)}", end="", flush=True)
                # swears that already have a word from the word list go in as already said; Gemma does the rest
                open_slots = [j for j, p in enumerate(s["picks"]) if p is None]
                line = marked(s)
                for j in reversed(range(len(s["swears"]))):
                    if s["picks"][j]:
                        line = _replace_nth(line, j, s["picks"][j])
                swears = [" ".join(w[2] for w in s["words"][f:l + 1]) for f, l in (s["swears"][j] for j in open_slots)]
                got = extract(line, gemma.rewrite(line))
                if not usable(got, swears):
                    got = extract(line, gemma.rewrite(line, "\n(Rewrite the whole line; replace only the bracketed "
                                                            "words, with clean words only.)"))
                if not usable(got, swears):
                    got = [default(sw) for sw in swears]
                    by = "a plain default"
                else:
                    by = "Gemma"
                for j, p in zip(open_slots, got):
                    s["picks"][j] = p
                    s["chosen_by"][j] = by
        print()


def _replace_nth(line, n, text):
    """Put `text` in place of the n-th [bracketed] swear (unbracketed: it is no longer to be chosen)."""
    found = list(re.finditer(r"\[[^\]]+\]", line))
    m = found[n]
    return line[:m.start()] + text + line[m.end():]


# ------------------------------------------------------------------ 3. saying them, in the writer

def _dots():
    import logging
    sys.path.insert(0, str(HERE / "speak_stubs"))
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    # notices meant for developers: PyTorch without triton (not on Windows), and transformers on the tokenizer's
    # text pattern - dots.tts was trained with the tokenizer exactly as it is, so it is left that way
    logging.getLogger("torch.utils.flop_counter").setLevel(logging.ERROR)
    import warnings
    warnings.filterwarnings("ignore", category=FutureWarning)
    import transformers
    transformers.logging.set_verbosity_error()
    from huggingface_hub import snapshot_download
    from dots_tts.edit_runtime import DotsTtsEditRuntime
    local = MODELS / "dots.tts.edit"
    if not (local / "model.safetensors").is_file():
        say("Downloading dots.tts, which says the clean words (5 GB, first use only)...")
        snapshot_download(DOTS, local_dir=str(local))
    return DotsTtsEditRuntime.from_pretrained(str(local), precision="bfloat16")


SETTINGS = [dict(), dict(num_steps=24, guidance_scale=2.0), dict(num_steps=32, guidance_scale=2.5)]


def _wav2vec2():
    import torch, torchaudio
    torch.hub.set_dir(str(MODELS / "torch"))           # kept with ProfMute's other models, not in the user's profile
    bundle = torchaudio.pipelines.WAV2VEC2_ASR_LARGE_LV60K_960H
    if not list((MODELS / "torch").rglob("*.pth")):
        say("Downloading the word-timing model (1.2 GB, first use only)...")
    model = bundle.get_model().to("cuda").eval()
    return bundle, model


def align(bundle, model, audio, rate, words):
    """[[word, start, end], ...] in seconds for `words` spoken in `audio` (mono)."""
    import torch, torchaudio
    labels = bundle.get_labels()
    index = {c: i for i, c in enumerate(labels)}
    up = lambda w: "".join(c for c in w.upper().replace("’", "'") if c in index and c not in "-|")
    x = torchaudio.functional.resample(torch.from_numpy(audio).float(), rate, bundle.sample_rate)[None].to("cuda")
    keep = [(i, up(w)) for i, w in enumerate(words) if up(w)]
    tokens = []
    for k, (_, ls) in enumerate(keep):
        if k:
            tokens.append(index["|"])
        tokens += [index[c] for c in ls]
    with torch.inference_mode():
        emission, _ = model(x)
        emission = torch.log_softmax(emission, dim=-1)
        path, scores = torchaudio.functional.forced_align(emission, torch.tensor([tokens], device="cuda"), blank=0)
    spans = torchaudio.functional.merge_tokens(path[0], scores[0].exp())
    step = x.shape[1] / emission.shape[1] / bundle.sample_rate
    out, s = [None] * len(words), 0
    for i, ls in keep:
        while s < len(spans) and spans[s].token == index["|"]:
            s += 1
        first = spans[s]
        s += len(ls) - 1
        out[i] = [letters(words[i]), first.start * step, spans[s].end * step]
        s += 1
    for i in range(len(out)):
        if out[i] is None:
            before = next((out[j][2] for j in range(i - 1, -1, -1) if out[j]), 0.0)
            out[i] = [letters(words[i]), before, before]
    return out


def speak(data, rate, top, dialogue, sentences, spans, voice, whisper_name, device, words, pm):
    """Say the chosen clean words in the actor's voice. data = the decoded track (frames x channels, integers up to
    `top`), still as in the movie; dialogue = the channels that carry the voices; spans = the muted spans
    [(start, end, ...)] (seconds). Sets s["result"] for each sentence and returns the stretches to lay over the
    muted track afterwards: [(first frame, frames, channels, new sound (frames x channels), blend (frames))]."""
    import gc
    import numpy as np, soundfile as sf, torch, torchaudio
    global PM
    PM = pm
    todo = [s for s in sentences if not s["muted"] and s.get("picks")]
    if not todo:
        return []
    tmp = Path(tempfile.mkdtemp(prefix=".profmute-speak-"))
    try:
        # the voice of each sentence, from its stretch of the movie, by the voice model already in use
        say(f"Separating the voice of {len(todo)} sentence(s)...")
        for s in todo:
            s0, s1 = s["words"][0][0], s["words"][-1][1]
            w0, w1 = max(0, int((s0 - 3.0) * rate)), min(len(data), int((s1 + 3.0) * rate))
            mix = data[w0:w1, dialogue].astype(np.float32) / top
            with torch.no_grad():
                bed = voice.voice_free(mix, rate)
            s["w0"], s["mix"], s["bed"] = w0, mix, bed
            v = (mix - bed).mean(axis=1)
            s["voice"] = v
            a, b = int((s0 - 0.15) * rate) - w0, int((s1 + 0.25) * rate) - w0
            s["offset"] = (w0 + max(0, a)) / rate                      # the sentence recording's start, movie clock
            s["sentence"] = v[max(0, a):b]
            sf.write(tmp / f"s{id(s)}.wav", s["sentence"], rate)
            s["target"] = marked(s, s["picks"])

        # dots.tts says each sentence again with the clean words; Whisper checks; up to three tries
        pending = list(todo)
        for attempt, opts in enumerate(SETTINGS, 1):
            if not pending:
                break
            say(f"Saying the clean words: {len(pending)} sentence(s)" + (f", try {attempt}" if attempt > 1 else "") + "...")
            rt = _dots()
            for n, s in enumerate(pending, 1):
                print(f"\r    speaking {n}/{len(pending)}", end="", flush=True)
                r = rt.generate_edit(source_audio_path=str(tmp / f"s{id(s)}.wav"), instruction=instruction(s, calm=s.get("calm")),
                                     **opts)
                a = r["audio"].float().cpu().numpy().reshape(-1) if torch.is_tensor(r["audio"]) else np.asarray(r["audio"]).reshape(-1)
                s["edited"] = torchaudio.functional.resample(torch.from_numpy(a), int(r["sample_rate"]), rate).numpy() \
                    if int(r["sample_rate"]) != rate else a
            print()
            del rt
            gc.collect(); torch.cuda.empty_cache()
            model, _ = pm.load_model(whisper_name, device)
            still = []
            for s in pending:
                x16 = torchaudio.functional.resample(torch.from_numpy(s["edited"].astype(np.float32)), rate, 16000).numpy()
                heard = pm.transcribe(model, x16)
                text = " ".join(w[2] for w in heard)
                flat = re.sub(r"[^a-z ]", "", text.lower())
                ok = not pm.find_hits(heard) and all(re.sub(r"[^a-z ]", "", p.lower()) in flat for p in s["picks"])
                s["yelled"] = False
                if ok:
                    s["yelled"], note = _yell(x16, heard, s["picks"])
                    s["pitches"] = s.get("pitches", []) + [note]
                    s["calm"] = s.get("calm") or s["yelled"]                  # the next tries ask for a calmer line
                    ok = not s["yelled"]
                if not ok:
                    still.append(s)
                s["heard"] = text
            del model
            gc.collect(); torch.cuda.empty_cache()
            pending = still
        for s in pending:
            tries = " / ".join(n for n in s.get("pitches", []) if n)
            s["result"] = f"muted: the clean word came out shouted ({tries})" if s.get("yelled") else \
                "muted: the spoken version did not pass the check"
        ready = [s for s in todo if s not in pending]
        if not ready:
            return []

        # exact word edges, in the original (over its whole stretch, with Whisper's words for it) and in the edit
        bundle, w2v = _wav2vec2()
        for s in ready:
            ww = [w for w in words if w[0] >= s["w0"] / rate - 0.01 and w[1] <= s["w0"] / rate + len(s["voice"]) / rate + 0.01]
            timed = align(bundle, w2v, s["voice"], rate, [w[2] for w in ww])
            first = next(i for i, w in enumerate(ww) if abs(w[0] - s["words"][0][0]) < 0.02)
            shift = s["offset"] - s["w0"] / rate
            s["ow"] = [[t[0], t[1] - shift, t[2] - shift] for t in timed[first:first + len(s["words"])]]
            s["ew"] = align(bundle, w2v, s["edited"], rate, s["target"].split())
        del w2v
        gc.collect(); torch.cuda.empty_cache()

        out = []
        for s in ready:
            try:
                piece = _cut_in(s, rate, spans, pm)
            except Exception as e:   # one sentence going wrong must not stop the movie: it stays muted
                s["result"] = f"muted: {type(e).__name__} while cutting in"
                continue
            if piece is None:
                continue
            out.append(piece)
            s["result"] = "spoken " + ", ".join(f'"{p}"' for p in s["picks"])
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        for s in sentences:
            for key in ("mix", "bed", "voice", "sentence", "edited"):
                s.pop(key, None)


def _features(x, rate):
    import numpy as np, torch, torchaudio
    hop = rate // 100
    mel = torchaudio.transforms.MelSpectrogram(rate, n_fft=2048, hop_length=hop, n_mels=64, f_min=60, f_max=8000)
    m = torch.log(mel(torch.from_numpy(x.astype(np.float32))) + 1e-5).T.numpy()
    return (m - m.mean(0)) / (m.std(0) + 1e-5)


def _dtw(a, b):
    import numpy as np
    d = np.sqrt(((a[:, None, :] - b[None, :, :]) ** 2).mean(axis=2))
    n, m = d.shape
    acc = np.full((n + 1, m + 1), np.inf)
    acc[0, 0] = 0
    for i in range(1, n + 1):
        row, prev, di = acc[i], acc[i - 1], d[i - 1]
        for j in range(1, m + 1):
            row[j] = di[j - 1] + min(prev[j - 1], prev[j], row[j - 1])
    i, j, path = n, m, []
    while i > 0 and j > 0:
        path.append((i - 1, j - 1))
        k = np.argmin((acc[i - 1, j - 1], acc[i - 1, j], acc[i, j - 1]))
        i, j = (i - 1, j - 1) if k == 0 else (i - 1, j) if k == 1 else (i, j - 1)
    return path[::-1]


def _stretch(x, factor, rate, pm):
    import numpy as np
    if abs(factor - 1) < 0.02:
        return x
    raw = subprocess.run([pm.FFMPEG, "-v", "error", "-f", "f32le", "-ar", str(rate), "-ac", "1", "-i", "-",
                          "-af", f"atempo={factor:.4f}", "-f", "f32le", "-"], input=x.astype(np.float32).tobytes(),
                         capture_output=True, check=True, creationflags=NO_WINDOW).stdout
    return np.frombuffer(raw, np.float32).copy()


def _cut_in(s, rate, spans, pm):
    """Where each clean word goes, and the new sound around it (see the module notes). None if the sentence's
    stretch would reach into another muted spot: it then stays muted."""
    import numpy as np, torch
    o, e, ow, ew = s["sentence"], s["edited"], s["ow"], s["ew"]
    hop = rate // 100
    off = s["offset"]
    lengths = [len(p.split()) for p in s["picks"]]
    # orig word index -> edit word index, for the words that did not change
    to_edit, shift = {}, 0
    for i in range(len(ow)):
        hit = next((j for j, (f, l) in enumerate(s["swears"]) if f <= i <= l), None)
        if hit is None:
            to_edit[i] = i + shift
        elif i == s["swears"][hit][1]:
            shift += lengths[hit] - (s["swears"][hit][1] - s["swears"][hit][0] + 1)

    def word_map(t):
        pairs = sorted((ow[i][j], ew[k][j]) for i, k in to_edit.items() if k < len(ew) for j in (1, 2))
        if len(pairs) < 2:
            return t
        xs, ys = zip(*pairs)
        if t < xs[0]:
            return ys[0] + t - xs[0]
        if t > xs[-1]:
            return ys[-1] + t - xs[-1]
        return float(np.interp(t, xs, ys))

    path = _dtw(_features(o, rate), _features(e, rate))
    oi = np.array([p[0] for p in path]); ej = np.array([p[1] for p in path])
    dtw_map = lambda t: float(np.median(ej[oi == min(oi[-1], max(0, int(t * rate / hop)))])) * hop / rate
    spec = torch.stft(torch.from_numpy(o.astype(np.float32)), n_fft=1024, hop_length=hop // 2, window=torch.hann_window(1024),
                      return_complex=True).abs().numpy() ** 2
    freqs = np.fft.rfftfreq(1024, 1 / rate)
    hi = np.sqrt(spec[(freqs >= 3000) & (freqs <= 10000)].sum(0))
    lo = np.sqrt(spec[(freqs >= 100) & (freqs < 3000)].sum(0))
    floor = np.percentile(hi, 15)

    cuts = []
    for j, (f, l) in enumerate(s["swears"]):
        # where this swear's clean words start in the edited sentence: earlier swears may have changed the count
        ke = f + sum(lengths[i] - (s["swears"][i][1] - s["swears"][i][0] + 1) for i in range(j))
        m = lengths[j]
        start, end = ow[f][1], ow[l][2]
        before = ow[f - 1][2] if f > 0 else start - 0.2
        after = ow[l + 1][1] if l + 1 < len(ow) else end + 0.3
        a_o = max(start - 0.06, (before + start) / 2) if before < start else start
        b_o = min(end + 0.06, (end + after) / 2) if after > end else end
        es, ee = ew[ke][1], ew[min(len(ew) - 1, ke + m - 1)][2]
        eb = ew[ke - 1][2] if ke > 0 else es - 0.2
        ea = ew[ke + m][1] if ke + m < len(ew) else ee + 0.3
        a_e = max(es - 0.06, (eb + es) / 2) if eb < es else es
        b_e = min(ee + 0.06, (ee + ea) / 2) if ea > ee else ee
        hs, he = s["hit"][j][0] - off, s["hit"][j][1] - off
        if not (start < he + 0.5 and end > hs - 0.1):         # the aligner latched onto other speech
            s["result"] = "muted: unsure exactly where the word is"
            return None
        # a hissing start (f, sh, s, th) counts as gap to the aligner: start before the hiss
        k = min(len(hi) - 1, int(start * rate / (hop // 2)))
        limit = max(0, k - int(0.15 * rate / (hop // 2)), int(((ow[f - 1][1] + ow[f - 1][2]) / 2 if f > 0 else 0) * rate / (hop // 2)))
        while k > limit and hi[k - 1] > 3 * floor and hi[k - 1] > 0.6 * lo[k - 1]:
            k -= 1
        a_o = min(a_o, k * (hop // 2) / rate - 0.025)
        if f > 0 and start - ow[f - 1][2] < 0.12:          # runs straight on from the word before
            a_o = min(a_o, ow[f - 1][2] - 0.03)
        da, db = dtw_map(a_o), dtw_map(b_o)
        mapper = dtw_map if 0.5 < (db - da) / max(1e-3, b_e - a_e) < 2 else word_map
        a_e, b_e = mapper(a_o), mapper(b_o)
        span = (min(spans[i][0] for i in s["spans"][j]), max(spans[i][1] for i in s["spans"][j]))
        core0, core1 = span[0] + 0.02 - off, span[1] - 0.30 - off       # ProfMute's own word: always covered
        # ... but a muted stretch reaching well into an unchanged word after the swear ("God damn ... it!") would cut
        # that word in half: dots.tts's version of the whole word goes in instead, at the word's own time. (Before the
        # swear, Whisper's early start only trims the end of the word before, which sounds fine: left as it is.)
        right, k = None, l + 1                            # where the words taken from dots.tts start
        while k < len(ow) and k in to_edit and to_edit[k] < len(ew) and core1 > ow[k][1] + 0.08:
            cuts.append((ow[k][1] - 0.03, ow[k][2] + 0.03, ew[to_edit[k]][1] - 0.03, ew[to_edit[k]][2] + 0.03, span))
            right = right or ow[k][1] - 0.03
            k += 1
        if right is not None:
            core1 = min(core1, right)
        if core0 < a_o or core1 > b_o:
            a_o, b_o = min(a_o, core0 - 0.02), max(b_o, core1)
            a_e, b_e = mapper(a_o), mapper(b_o)
        if right is not None and b_o > right:             # the swear's own cut stops where the next word's starts
            b_o, b_e = right, mapper(right)
        n = l + 1                                         # the actor's next word stays: dots.tts's copy of it must
        if right is None and n < len(ow) and n in to_edit and to_edit[n] < len(ew) and b_o <= ow[n][1] + 0.01:
            b_e = min(b_e, max(ew[to_edit[n]][1], ee))    # not come too ("Darn it" + the actor's "it" = "Darn it it")
        cuts.append((a_o, b_o, a_e, b_e, span))

    loud = lambda x: float(np.sqrt(np.mean(x ** 2)) + 1e-9)
    z0 = min(min(c[0] + off, c[4][0]) for c in cuts) - 0.05
    z1 = max(max(c[1] + off, c[4][1]) for c in cuts) + 0.05
    mine = {i for group in s["spans"] for i in group}
    if any(i not in mine and sp[1] > z0 and sp[0] < z1 for i, sp in enumerate(spans)):
        s["result"] = "muted: another muted word is too close"
        return None
    first, last = int(round(z0 * rate)), int(round(z1 * rate))
    zlen = last - first
    fade = int(0.015 * rate)

    def window(start, length):
        w = np.zeros(zlen, np.float32)
        a, b = max(0, start), min(zlen, start + length)
        if b > a:
            w[a:b] = 1
            r = min(fade, (b - a) // 2)
            w[a:a + r] = np.linspace(0, 1, r)
            w[b - r:b] = np.linspace(1, 0, r)
        return w

    lo_w = first - s["w0"]
    if lo_w < 0 or lo_w + zlen > len(s["mix"]):
        s["result"] = "muted: too close to the start or end of the sound"
        return None
    rebuilt = s["mix"][lo_w:lo_w + zlen].astype(np.float32).copy()          # the original sound ...
    bed = s["bed"][lo_w:lo_w + zlen]
    for a_o, b_o, a_e, b_e, span in cuts:
        new = e[max(0, int(a_e * rate)):max(0, int(b_e * rate))].copy()     # never wrap round to the end
        keep_o = np.concatenate([o[:int(a_o * rate)], o[int(b_o * rate):]])
        keep_e = np.concatenate([e[:int(a_e * rate)], e[int(b_e * rate):]])
        gain = loud(keep_o) / loud(keep_e) if min(len(keep_o), len(keep_e)) > 0.3 * rate else 1.0
        new *= min(4.0, max(0.25, gain))
        slot = (b_o - a_o) * rate
        new = _stretch(new, min(1.3, max(0.85, len(new) / slot)), rate, pm)
        sa = int(round((a_o + off) * rate)) - first
        gap = window(sa, int(round(slot)))
        put = window(sa, len(new))
        rebuilt = rebuilt * (1 - gap[:, None]) + bed * gap[:, None]      # ... the whole gap voice-free ...
        n = min(len(new), zlen - sa)
        rebuilt[sa:sa + n] += (new[:n] * put[sa:sa + n])[:, None]        # ... and the clean word in it
    edge = np.ones(zlen, np.float32)
    edge[:fade] = np.linspace(0, 1, fade)
    edge[-fade:] = np.linspace(1, 0, fade)
    return first, zlen, rebuilt, edge
