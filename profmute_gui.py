"""profmute_gui - a small window for profmute.py.

Start it by double-clicking ProfMute.exe (a small launcher, see launcher\\ProfMute.cs), or:
uv run python profmute_gui.py
It runs profmute.py as a separate process (one per movie) and shows its output, so everything the
command line version does applies here too. The word list (words.txt) and the model list
(models.txt) sit next to this file and are meant to be edited.
"""
import bisect, codecs, hashlib, json, os, queue, re, shutil, subprocess, sys, tempfile, threading, time
import tkinter as tk
from collections import Counter
from pathlib import Path
from tkinter import filedialog, font, messagebox, ttk

try:
    import winsound
except ImportError:  # not on Windows: no sounds
    winsound = None

import profmute  # for its defaults and file lookups; the work itself runs in a separate process

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "profmute.py"
SETTINGS = HERE / "profmute_gui.json"   # remembers the choices made in the window
ICON = HERE / "profmute.ico"
WORDS = HERE / "words.txt"
MODELS = HERE / "models.txt"
VOICE_MODELS = HERE / "voice-models.txt"
REVIEW = HERE / "review"   # a batch's saved analyses and their questions, between listening and writing
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
VIDEO_EXT = (".mkv", ".mp4", ".m4v", ".avi", ".mov", ".ts", ".webm")
VIDEO_GLOB = " ".join("*" + e for e in VIDEO_EXT)
VIDEOS = [("Video files", VIDEO_GLOB), ("All files", "*.*")]
SUBS = [("Subtitle files", "*.srt"), ("All files", "*.*")]
DARK = dict(bg="#1e1e1e", field="#2b2b2b", fg="#e6e6e6", muted="#9a9a9a", border="#3c3c3c",
            button="#333333", hover="#404040", accent="#3b82f6", disabled="#6b6b6b")
CONFIRM_TIP = ("Whisper sometimes puts a word in the wrong spot.\n\n"
               "With this on, every word it finds is listened to a second time on its own. If the two "
               "listens disagree, a third one settles it, and only the place two of them agree on is muted.\n\n"
               "Takes a little longer.")
ASK_TIP = ("A conflict is a word Whisper heard that the subtitles do not have.\n\n"
           "On: you decide each one, hearing it first.\n"
           "Off: you are never asked. Three listens decide, and the word is muted only if "
           "two of them hear it in the same place.")
TRANSCRIPT_TIP = ("On: before a clean copy is written, you get the movie's whole transcript to check, as the clean copy "
                  "will have it: every muted word shows as f*****, so a swear you can still read was missed.\n\n"
                  "Click a word to mute it (or drag across several and press Mute selected), click a muted word to "
                  "keep it in this movie, search for any word, and click a time to hear that line.\n\n"
                  "In a batch the transcripts come after the questions, before the clean copies are written, so the "
                  "batch can still run while you are away.")
LATER_TIP = ("On: a batch runs in three rounds, so it can run while you are away:\n"
             "1. Every movie is listened to and checked, without asking anything.\n"
             "2. All the questions about all the movies (conflicts and unresolved words, if you chose to be asked) "
             "come together, one after another, each with its movie's name and Play buttons.\n"
             "3. Every clean copy is written with your answers, without asking anything.\n\n"
             "Your answers are saved as you give them: if you stop halfway, start the same batch again and only the "
             "questions you have not answered come back (the movies are not listened to again).\n\n"
             "Off: each movie is listened to, asked about and written before the next one starts, so the batch "
             "waits for you at each movie with questions.")
UNRESOLVED_TIP = ("An unresolved word is one the subtitles have but Whisper never heard, even after "
                  "listening to that line again. ProfMute knows which subtitle line it is in, but not exactly when it is said.\n\n"
                  "On: ProfMute plays a sound and shows you each one. You can play the line, then mute the whole "
                  "line, mute only its best guess at the spot, or leave it. In a batch, this pauses the batch.\n"
                  "Off: nothing is muted. The lines are listed in the log under UNRESOLVED for you to check by ear.")
OWN_FOLDER_TIP = ("On: the clean copies keep the folders they were in, below the folder you added, so a library "
                  "stays a library:\n\n"
                  "     TV\\Show\\Season 01\\Episode.mkv\n"
                  "     -> Output folder\\Show\\Season 01\\Episode.clean.mkv\n\n"
                  "A movie with no folder of its own (added with Add files, or lying loose in the added folder) "
                  "gets one named after it:\n\n"
                  "     Output folder\\Iron Man\\Iron Man.clean.mkv\n\n"
                  "The clean subtitles go next to each clean copy.\n"
                  "Off: every clean copy goes straight into the output folder.\n\n"
                  "Needs an output folder.")
LOG_BESIDE_TIP = ("The log lists every spot that was muted, with its time, plus the conflicts and unresolved words.\n\n"
                  "On: each movie's log is saved in the same folder as its clean copy.\n"
                  "Off: all logs go into the Log folder below, which starts as a \"log\" folder next to ProfMute.")
TIPS = {
    "movie": "The movie to clean. It is only read, never changed.",
    "srt": "Subtitles for this movie (a .srt file). They double-check what Whisper hears, and the clean subtitle "
           "file is made from them.\n\nUse an accurate one, ideally from the disc or the official release. "
           "Machine-made subtitles often leave out swears, and every swear Whisper hears that they leave out "
           "becomes a conflict to decide.\n\nLeave empty and ProfMute uses a .srt next to the movie with the same name, "
           "or else the English subtitles inside the movie file.",
    "out": "Where the clean copy is saved: the movie with the words on your list muted.\n\n"
           "Fills itself in as <movie name>.clean.mkv next to the movie. It is always an .mkv file.",
    "out_srt": "Where the clean subtitles are saved: the same subtitles with the words on your list deleted.\n\n"
               "Fills itself in next to the clean copy, under the name media players pair with it. "
               "Only written when the movie has subtitles.",
    "list": "The movies to clean. Only the ticked ones are done, one after another from the top.\n\n"
            "Click a box to tick or untick it, or select rows and press Space. A folder's box ticks or unticks "
            "everything inside it, so one click takes a whole show or season.\n\n"
            "\"Subtitles\" shows which subtitles each movie will use, \"Status\" how it went.",
    "add_files": "Add movies to the list, ticked. You can pick .srt files here too: each one is given to the movie "
                 "in the list that has the same name.",
    "add_folder": "Add a folder, such as your Movies or TV folder, with every movie in it and in the folders inside "
                  "it, shown as a tree. Nothing is ticked yet: tick the movies, shows or seasons to clean.\n\n"
                  "Subtitle files next to the movies are found by themselves. Clean copies made earlier are left out.",
    "pop_out": "Open the list in a window of its own, which you can make as big as you like or move to another "
               "screen. Close that window, or press Put list back, to return the list here.",
    "dock": "Return the list to this tab.",
    "tick_all": "Tick every movie in the list.",
    "untick_all": "Untick every movie in the list.",
    "set_subtitle": "Choose a subtitle file by hand for the movies selected in the list.",
    "remove": "Take the selected movies or folders off the list. Nothing is deleted from your disk.",
    "clear": "Empty the list. Nothing is deleted from your disk.",
    "batch_out": "Where the clean copies of the batch are saved. Leave empty to put each one next to its own movie.",
    "log_dir": "The folder for logs when they are not put next to the clean copies (untick the box above).\n\n"
               "Starts as a \"log\" folder next to ProfMute.",
    "words": "The list of words and phrases to mute. It is a plain text file you can change.\n\n"
             "Browse picks a different list; Edit opens this one.",
    "words_edit": "Open the word list in your text editor. Changes apply to the next run.",
    "model": "The speech recognition model that listens to the movie. Bigger models hear more accurately but are "
             "slower and a bigger download. A model downloads itself the first time it is used.\n\n"
             "On a PC without an NVIDIA graphics card, pick a small one.",
    "voice_model": "The AI model that takes the voice out of a muted moment while keeping the music and effects, "
                   "when \"Remove only the voice with AI\" is on.\n\nThe recommended one sounded best in testing; "
                   "the other is a second choice. A model downloads itself the first time it is used. The list "
                   "comes from voice-models.txt next to ProfMute.",
    "padding": "Extra silence added around each muted word, because speech recognition marks where a word "
               "starts and ends only roughly.",
    "pad_before": "Seconds of extra silence before each muted word.\n\nRaise it if you can hear the start of a "
                  "word; lower it if the end of the word before gets cut off.",
    "pad_after": "Seconds of extra silence after each muted word.\n\nRaise it if you can hear the end of a "
                 "word; lower it if the start of the next word gets cut off.",
    "start": "Clean the movie on the One movie tab, or every ticked movie in the Batch list, whichever tab is showing.",
    "cancel": "Stop the run. A clean copy that was only half written is deleted. Your original movie is never touched.",
    "dark": "Switch the window between dark and light colours.",
}
FADE_TIP = ("On: the sound fades out over a few hundredths of a second just before each muted word and fades "
            "back in just after it, so the mute starts and ends smoothly instead of with a click. The word itself "
            "stays fully silent.\n\nOff: the sound switches off and on instantly.")
DIALOGUE_TIP = ("For movies with surround sound (5.1, 7.1 and similar), where the dialogue has a channel of its own.\n\n"
                "On: only that dialogue (centre) channel is silenced for each word, so music and sound effects in "
                "the other speakers keep playing.\n"
                "Off: every channel is silenced, so music and effects drop out with the word too.\n\n"
                "Stereo movies have no separate dialogue channel, so all of their sound is changed. If you can still "
                "faintly hear a word in some movie, its mix puts some dialogue in the other speakers too: turn this off.")
FRONT_TIP = ("Some surround mixes put a little of the dialogue in the front left and right speakers too, so a "
             "word silenced in the centre channel can still be faintly heard.\n\n"
             "On: for every word, ProfMute also listens to the front left and right speakers on their own. Where "
             "it hears the word there too, it changes those speakers as well for that word.\n"
             "Off: only the centre channel is changed.\n\n"
             "Only used with \"Mute only the dialogue channel\" on a surround movie. Takes a little longer.")
SPEAK_TIP = ("On: instead of leaving a gap, a clean word is said in its place in the actor's own voice, inside "
             "their own sentence: \"get the heck out of my bar\", \"you're a freaking joke\". An AI picks the word "
             "to fit the sentence (your own choices in the word list's [replacements] section come first), another "
             "AI says it, and each one is checked by listening to it again.\n"
             "The clean subtitles say the spoken word. A word that comes out yelled (the AI copies a scream "
             "badly) is tried again calmer; if it still yells, or does not pass the check, it stays muted as usual.\n\n"
             "Needs an NVIDIA graphics card and \"Remove only the voice with AI\". The first time, it downloads "
             "about 14 GB of AI models. It adds roughly 10 seconds per sentence with a swear, so 5 to 10 minutes "
             "for a typical movie and up to about 40 minutes for one full of swearing.")
SEPARATE_TIP = ("On: instead of silencing a word, an AI voice model takes only the voice out of those moments, "
                "so the music and sound effects underneath keep playing. It works on stereo movies too, and on a "
                "surround movie it works on whichever speakers are being changed.\n"
                "Off: the words are silenced.\n\n"
                "The voice model downloads itself the first time it is used (about 1 GB). With an NVIDIA graphics "
                "card it adds about half a minute to a movie; on the processor alone it takes much longer.")
PREVIEW_TIP = ("A trial run. ProfMute does all the listening and writes the log, so you can see what it would "
               "mute, but it writes no video and no subtitle file, and it never stops to ask you anything.")
SKIP_TIP = ("On: a movie whose clean copy already exists is left alone, so a batch that was interrupted can "
            "simply be started again.\nOff: every movie is done again and its clean copy replaced.")
BUTTON_TIPS = {
    "play": "Hear the few seconds around the word, as they are in the original movie.",
    "mute": "Silence this word in the clean copy, at the place Whisper heard it.",
    "leave": "Change nothing here. The word stays audible in the clean copy.",
    "auto": "Stop asking for this movie. Three listens decide this conflict and the remaining ones: "
            "a word is muted only if two of them hear it in the same place.",
    "play_line": "Hear the whole subtitle line, as it is in the original movie.",
    "play_spot": "Hear only the stretch that 'Mute the estimated spot' would silence, to judge whether the guess is right.",
    "line": "Silence the whole subtitle line in the clean copy. Certain to cover the word, "
            "but the other words of the line go silent too.",
    "spot": "Silence only ProfMute's best guess at where the word is, worked out from the words around it "
            "that Whisper did hear. Cuts much less, but can miss the word. Use 'Play the spot' first.",
    "leave_unresolved": "Mute nothing for this line. It stays listed under UNRESOLVED in the log.",
    "leave_rest": "Stop asking for this movie. This line and the remaining unresolved ones are left as they are.",
    "back": "Go back to the question before and answer it again. Nothing is decided until the last question is "
            "answered, so any answer can still be changed.",
}
ANSWER_WORDS = {"mute": "Mute it", "leave": "Leave it", "auto": "Decide the rest automatically", "line": "Mute the whole line",
                "spot": "Mute the estimated spot"}   # an earlier answer, as shown when going back to it


def load_settings():
    try:
        data = json.loads(SETTINGS.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(**changes):
    try:
        SETTINGS.write_text(json.dumps({**load_settings(), **changes}))
    except OSError:
        pass  # not being able to remember a choice is no reason to complain


def saved_dark():
    settings = load_settings()
    if "dark" in settings:
        return bool(settings["dark"])
    try:  # first launch: follow the Windows light/dark app setting
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except Exception:
        return False


def size_text(size):
    if not size:
        return "size unknown"
    return f"{size / 1e9:.1f} GB" if size >= 950e6 else f"{round(size / 1e6, -1 if size >= 95e6 else 0):.0f} MB"


def model_label(row):
    flag = "   (unknown model name)" if row.get("problem") else \
           "   (downloads on first use)" if row.get("downloaded") is False else ""
    return f"{row['name']}   -   {size_text(row.get('size'))}   -   {row['note']}{flag}"


def voice_label(row, recommended):
    flag = "   (downloads on first use)" if row.get("downloaded") is False else ""
    return f"{row['name']}   -   {size_text(row.get('size'))}" + ("   -   recommended" if recommended else "") + flag


def review_file(movie, out):
    """Where a batch keeps one movie's analysis until its clean copy is written: one file per movie and clean copy."""
    key = hashlib.sha1(f"{os.path.normcase(str(movie))}|{os.path.normcase(str(out))}".encode()).hexdigest()[:16]
    return REVIEW / f"{key}.json"


def prune_reviews(days=30):
    """Analyses left over from batches never finished: removed after a month, with their clips."""
    if not REVIEW.is_dir():
        return
    for f in REVIEW.glob("*.json"):
        try:
            if time.time() - f.stat().st_mtime > days * 86400:
                profmute.drop_review(str(f))
        except OSError:
            pass


def read_review(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def open_questions(data):
    """The questions in a saved analysis still waiting for an answer: [("conflicts" | "unresolved", info), ...].
    An answer of "auto" (decide the rest by yourself) answers the ones after it too."""
    out = []
    for part, items in (("conflicts", data.get("pending", [])), ("unresolved", data.get("questions", []))):
        answers = data.get("answers", {}).get(part, {})
        if "auto" not in answers.values():
            out += [(part, q["info"]) for q in items if str(q["info"]["n"]) not in answers]
    return out


def is_our_output(path):
    """A file ProfMute wrote itself (<name>.clean.mkv, <name>.clean.en.srt): never batch input."""
    name = path.name.lower()
    return name.endswith(".clean" + path.suffix.lower()) or ".clean." in name


def scan_folder(folder):
    """Every movie in a folder and its subfolders, skipping clean copies made earlier."""
    found = []
    for base, _, names in os.walk(folder):
        for name in sorted(names):
            p = Path(base) / name
            if p.suffix.lower() in VIDEO_EXT and not is_our_output(p):
                found.append(p)
    return found


def scan_library(folder):
    """scan_folder, plus each movie's subtitle file next to it (the one profmute.sidecar_srt would pick, or None),
    found from the folder listing that is read anyway: one listing per folder, which counts on a network share."""
    found = []
    for base, dirs, names in os.walk(folder):
        dirs.sort(key=str.lower)
        lower = {n.lower(): n for n in names}
        for name in sorted(names, key=str.lower):
            p = Path(base) / name
            if p.suffix.lower() in VIDEO_EXT and not is_our_output(p):
                side = next((lower[s] for s in (p.stem.lower() + x for x in (".en.srt", ".eng.srt", ".srt"))
                             if s in lower), None)
                found.append((p, Path(base) / side if side else None))
    return found


def fits_screen(widget, geometry):
    """A remembered window size and place ("WxH+X+Y") is still on the screens there are now (one may be unplugged)."""
    m = re.fullmatch(r"(\d+)x(\d+)([+-]+\d+)([+-]+\d+)", geometry or "")
    if not m:
        return False
    w, h, x, y = (int(v.replace("+", "")) for v in m.groups())
    try:   # all monitors together
        import ctypes
        metric = ctypes.windll.user32.GetSystemMetrics
        left, top, width, height = metric(76), metric(77), metric(78), metric(79)
    except Exception:
        left, top, width, height = 0, 0, widget.winfo_screenwidth(), widget.winfo_screenheight()
    return (w <= width and h <= height and left - 20 <= x and x + 100 <= left + width
            and top - 20 <= y and y + 50 <= top + height)


def box_images(size, border, fill, mark):
    """The three checkbox pictures for the batch tree: unticked, ticked, partly ticked (a folder)."""
    images = {}
    for state in ("off", "on", "part"):
        img = tk.PhotoImage(width=size + max(2, size // 4), height=size)   # a little room before the text
        img.put(fill, to=(1, 1, size - 1, size - 1))
        for box in ((0, 0, size, 1), (0, size - 1, size, size), (0, 0, 1, size), (size - 1, 0, size, size)):
            img.put(border, to=box)
        if state == "part":
            inset = round(size * 0.27)
            img.put(mark, to=(inset, inset, size - inset, size - inset))
        elif state == "on":
            thick = max(2, round(size / 7))
            points = ((0.2, 0.5), (0.42, 0.72), (0.8, 0.28))
            for (x0, y0), (x1, y1) in zip(points, points[1:]):
                steps = size * 2
                for i in range(steps + 1):
                    x = round((x0 + (x1 - x0) * i / steps) * size)
                    y = round((y0 + (y1 - y0) * i / steps) * size)
                    img.put(mark, to=(x - thick // 2, y - thick // 2, x - thick // 2 + thick, y - thick // 2 + thick))
        images[state] = img
    return images


def srt_belongs_to(srt, movie):
    """Movie.srt, Movie.en.srt, Movie.eng.sdh.srt ... all belong to Movie.mkv, whatever folder they are in."""
    name, stem = srt.name.lower(), movie.stem.lower()
    return name == stem + ".srt" or name.startswith(stem + ".")


class Tooltip:
    """A short explanation that appears while the mouse rests on a widget."""
    def __init__(self, widget, text):
        self.widget, self.text, self.tip, self.timer = widget, text, None, None
        widget.tooltip = self
        widget.bind("<Enter>", lambda e: self.schedule(), add="+")
        widget.bind("<Leave>", lambda e: self.hide(), add="+")
        widget.bind("<ButtonPress>", lambda e: self.hide(), add="+")
        widget.bind("<Destroy>", lambda e: self.hide(), add="+")

    def schedule(self):
        self.hide()
        self.timer = self.widget.after(500, self.show)

    def show(self):
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{self.widget.winfo_rootx() + 20}+{self.widget.winfo_rooty() + self.widget.winfo_height() + 6}")
        tk.Label(self.tip, text=self.text, justify="left", wraplength=380, padx=10, pady=8, relief="solid", borderwidth=1,
                 background="#fffbe6", foreground="#1e1e1e").pack()

    def hide(self):
        try:
            if self.timer:
                self.widget.after_cancel(self.timer)
            if self.tip:
                self.tip.destroy()
        except tk.TclError:
            pass  # the widget went away with its window
        self.timer = self.tip = None


HIDDEN = "\u200b"   # zero width: keeps the place of a word the transcript does not show


def mask(word):
    """A muted word as the transcript shows it: its first letter, the rest as stars ("f******,"). Same length."""
    out, first = [], True
    for ch in word:
        if ch.isalnum():
            out.append(ch if first else "*")
            first = False
        else:
            out.append(ch)
    return "".join(out)


def transcript_lines(words):
    """Whisper's words grouped into lines to read: a new line after a pause, after a sentence of six words or
    more, or after sixteen words. -> [[word index, ...], ...]"""
    lines, line = [], []
    for i, (s, e, text) in enumerate(words):
        if line and (s - words[line[-1]][1] > 1.0 or len(line) >= 16 or
                     (len(line) >= 6 and words[line[-1]][2].rstrip('"\')').endswith((".", "?", "!")))):
            lines.append(line)
            line = []
        line.append(i)
    if line:
        lines.append(line)
    return lines


class Transcript:
    """The last check before a clean copy is written: the movie's dialogue as Whisper heard it, as the clean copy
    will have it. A muted word shows masked ("f******"), so a swear that can be read plainly is one that was missed.
    Click a word to mute it, or a muted one to keep it; drag across several words and press "Mute selected" for a
    phrase; search; click a time to hear that line from the movie. done(data) gets the saved analysis back with
    the changes ("picks") in it."""

    def __init__(self, app, job, data, done):
        self.app, self.job, self.data, self.done = app, job, data, done
        self.words = [tuple(w[:3]) for w in data["words"]]
        starts = [w[0] for w in self.words]

        def under(spans):   # the words each stretch of time covers
            out = set()
            for s, e, *_ in spans:
                k = max(0, bisect.bisect_right(starts, s) - 1)
                while k < len(self.words) and self.words[k][0] < e:
                    if self.words[k][1] > s:
                        out.add(k)
                    k += 1
            return out
        self.listed = under(profmute.review_mutes(data)[0])
        picks = data.get("picks") or {}
        self.kept = under(picks.get("keep", [])) & self.listed
        self.picked = under(picks.get("mute", []))
        # "Speak a clean word": what will be said instead of each swear, the AI's word or yours ("" = just mute it)
        yours = {(round(x[0], 2), round(x[1], 2)): x[3] for x in picks.get("say", [])}
        self.says = []        # [word indexes, swear, the AI's word, your word or None, start, end]
        for s, e, swear, word, by in data.get("say", []):
            covered = sorted(under([(s, e)]))
            if covered:
                self.says.append([covered, swear, word, yours.get((round(s, 2), round(e, 2))), s, e])
        self.say_of = {i: n for n, g in enumerate(self.says) for i in g[0]}
        self.lines = transcript_lines(self.words)
        self.first = {line[0] for line in self.lines}
        self.found, self.current, self.word_win = [], -1, None

        dark = app.dark.get()
        win = self.win = tk.Toplevel(app.root)
        win.title(f"ProfMute - transcript of {job['title']}")
        win.geometry(f"{min(1100, app.root.winfo_screenwidth() - 80)}x{min(760, app.root.winfo_screenheight() - 120)}")
        win.minsize(640, 400)
        if dark:
            win.configure(background=DARK["bg"])
        box = ttk.Frame(win, padding=12)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text=job["title"], style="Big.TLabel").pack(anchor="w")
        ttk.Label(box, style="Hint.TLabel", wraplength=1000, justify="left", text=(
            "The dialogue as the clean copy will have it: muted words show as f*****, so a swear you can read "
            "plainly here was missed. Click a word to mute it, or click a muted word to keep it in this movie. "
            "For several words, drag across them and press Mute selected. Click a time to hear that line." +
            (" Purple words will be said in place of a swear: right-click one to choose another word, or to just "
             "mute it." if self.says else ""))).pack(anchor="w", pady=(2, 8))

        find = ttk.Frame(box)
        find.pack(fill="x", pady=(0, 6))
        ttk.Label(find, text="Find").pack(side="left")
        self.query = tk.StringVar()
        entry = ttk.Entry(find, textvariable=self.query, width=34)
        entry.pack(side="left", padx=6)
        entry.bind("<Return>", lambda e: self.step(1))
        entry.bind("<Shift-Return>", lambda e: self.step(-1))
        self.query.trace_add("write", lambda *_: self.search())
        ttk.Button(find, text="Previous", command=lambda: self.step(-1)).pack(side="left")
        ttk.Button(find, text="Next", command=lambda: self.step(1)).pack(side="left", padx=6)
        self.count = tk.StringVar()
        ttk.Label(find, textvariable=self.count).pack(side="left", padx=6)
        self.find_muted = tk.BooleanVar(value=False)
        also = ttk.Checkbutton(find, text="Include muted words", variable=self.find_muted, command=self.search)
        also.pack(side="right")
        Tooltip(also, "Off: the search skips muted words, so it only finds what will still be heard in the clean "
                      "copy, which is where a missed word hides.\nOn: it finds muted words too, for one to keep.")

        middle = ttk.Frame(box)
        middle.pack(fill="both", expand=True)
        colors = dict(bg=DARK["field"], fg=DARK["fg"]) if dark else dict(bg="white", fg="black")
        text = self.text = tk.Text(middle, wrap="word", font=("Segoe UI", 11), cursor="arrow", padx=10, pady=8,
                                   background=colors["bg"], foreground=colors["fg"], insertbackground=colors["fg"],
                                   relief="flat", highlightthickness=0, spacing1=2, spacing3=2)
        scroll = ttk.Scrollbar(middle, command=text.yview)
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.configure(yscrollcommand=scroll.set)
        pick = (lambda d, l: d if dark else l)
        text.tag_configure("time", foreground=pick("#8b949e", "#6b7280"), font=("Consolas", 10))
        text.tag_configure("listed", foreground=pick("#7aa2f7", "#1d4ed8"))
        text.tag_configure("picked", foreground=pick("#4ade80", "#15803d"), underline=True)
        text.tag_configure("kept", foreground=pick("#fbbf24", "#b45309"), underline=True)
        text.tag_configure("spoken", foreground=pick("#c084fc", "#7e22ce"))
        text.tag_configure("found", background=pick("#5b4a12", "#fde68a"))
        text.tag_configure("current", background=pick("#a16207", "#facc15"))
        text.tag_raise("current")
        text.tag_bind("time", "<Enter>", lambda e: text.configure(cursor="hand2"))
        text.tag_bind("time", "<Leave>", lambda e: text.configure(cursor="arrow"))
        text.bind("<ButtonRelease-1>", self.clicked)
        text.bind("<Button-3>", self.right_clicked)

        bottom = ttk.Frame(box)
        bottom.pack(side="bottom", fill="x", pady=(8, 0), before=middle)   # its room first: the transcript gets the rest
        legend = ttk.Frame(bottom)
        legend.pack(fill="x")
        for label, tag in (("muted by the word list or your answers", "listed"), ("muted by you", "picked"),
                           ("kept by you", "kept")) + ((("said instead (right-click to change)", "spoken"),) if self.says else ()):
            sample = tk.Label(legend, text="■ " + label, foreground=text.tag_cget(tag, "foreground"),
                              background=DARK["bg"] if dark else app.light_bg)
            sample.pack(side="left", padx=(0, 14))
        actions = ttk.Frame(bottom)
        actions.pack(fill="x", pady=(6, 0))
        self.summary = tk.StringVar()
        ttk.Label(actions, textvariable=self.summary).pack(side="left")
        ttk.Button(actions, text="Done", command=self.finish).pack(side="right")
        self.mute_btn = ttk.Button(actions, text="Mute selected", command=self.mute_selected)
        self.mute_btn.pack(side="right", padx=6)
        Tooltip(self.mute_btn, "Mute the words you dragged across, as one phrase.")
        win.protocol("WM_DELETE_WINDOW", self.finish)
        app.title_bar(win)
        self.render()
        entry.focus_set()

    # ---- what each word shows
    def muted(self, i):
        return (i in self.listed and i not in self.kept) or i in self.picked

    def spoken(self, g):
        """A swear will be said instead only while all its words are still muted as the list or your answers had it."""
        return all(k in self.listed and k not in self.kept and k not in self.picked for k in g[0])

    def look(self, i):
        tag = "picked" if i in self.picked else "kept" if i in self.kept else "listed" if i in self.listed else None
        word = self.words[i][2]
        shown = mask(word) if self.muted(i) else word
        g = self.says[self.say_of[i]] if i in self.say_of else None
        if g and self.spoken(g) and (g[2] if g[3] is None else g[3]):
            if i != g[0][0]:
                return HIDDEN, "spoken"       # the clean word stands for the whole swear, shown once
            said = g[2] if g[3] is None else g[3]
            shown, tag = said + re.search(r"[^\w']*$", self.words[g[0][-1]][2]).group(), "spoken"
        return shown, tag

    def gap(self, i, shown):
        """The space before word i: none before a line's first word, or before one hidden in a clean word."""
        return HIDDEN if i in self.first or shown == HIDDEN else " "

    def render(self):
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        for n, line in enumerate(self.lines):
            t.insert("end", profmute.stamp(self.words[line[0]][0])[:8], ("time", f"line{n}"))
            t.tag_bind(f"line{n}", "<Button-1>", lambda e, n=n: self.play(n))
            t.insert("end", " ")
            for i in line:
                shown, tag = self.look(i)
                t.insert("end", self.gap(i, shown), (f"s{i}",))
                t.insert("end", shown, (f"w{i}",) + ((tag,) if tag else ()))
            t.insert("end", "\n")
        t.configure(state="disabled")
        self.tell()

    def redraw(self, i):
        t = self.text
        shown, tag = self.look(i)
        t.configure(state="normal")
        start, end = t.tag_ranges(f"w{i}")
        t.delete(start, end)
        t.insert(start, shown, (f"w{i}",) + ((tag,) if tag else ()))
        start, end = t.tag_ranges(f"s{i}")
        t.delete(start, end)
        t.insert(start, self.gap(i, shown), (f"s{i}",))
        t.configure(state="disabled")

    def refresh(self, i):
        """Show word i again, with the rest of its swear when a clean word stands for it."""
        for k in (self.says[self.say_of[i]][0] if i in self.say_of else [i]):
            self.redraw(k)

    def tell(self):
        muted = sum(self.muted(i) for i in range(len(self.words)))
        chosen = sum(g[3] is not None for g in self.says)
        self.summary.set(f"{muted} word(s) muted   ·   you: {len(self.picked)} muted, {len(self.kept)} kept"
                         + (f", {chosen} word(s) chosen" if self.says else ""))

    # ---- changing it
    def word_at(self, index):
        for tag in self.text.tag_names(index):
            if tag.startswith("w") and tag[1:].isdigit():
                return int(tag[1:])
        return None

    def clicked(self, event):
        if self.text.tag_ranges("sel"):   # dragged across words: "Mute selected" does those
            return
        i = self.word_at(f"@{event.x},{event.y}")
        if i is not None:
            self.toggle(i)

    def toggle(self, i):
        """One word: mute it, or keep it if it is muted; again to undo."""
        if i in self.picked:
            self.picked.discard(i)
        elif i in self.kept:
            self.kept.discard(i)
        elif i in self.listed:
            self.kept.add(i)
        else:
            self.picked.add(i)
        self.refresh(i)
        self.tell()

    def mute_selected(self):
        sel = self.text.tag_ranges("sel")
        if not sel:
            return
        start, end = sel
        chosen = {i for i in range(len(self.words)) if self.text.tag_ranges(f"w{i}")
                  and self.text.compare(self.text.tag_ranges(f"w{i}")[1], ">", start)
                  and self.text.compare(self.text.tag_ranges(f"w{i}")[0], "<", end)}
        for i in sorted(chosen):
            if i in self.listed:
                self.kept.discard(i)
            else:
                self.picked.add(i)
            self.refresh(i)
        self.text.tag_remove("sel", "1.0", "end")
        self.tell()

    def right_clicked(self, event):
        i = self.word_at(f"@{event.x},{event.y}")
        if i is not None and i in self.say_of and self.spoken(self.says[self.say_of[i]]):
            self.choose_word(self.says[self.say_of[i]])

    def choose_word(self, g):
        """What to say instead of one swear: your word, the AI's, or nothing (just mute it)."""
        dark = self.app.dark.get()
        win = tk.Toplevel(self.win)
        win.title("ProfMute - what to say instead")
        win.transient(self.win)
        win.resizable(False, False)
        if dark:
            win.configure(background=DARK["bg"])
        box = ttk.Frame(win, padding=16)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text=f"Instead of “{g[1].strip(',.?!')}”, say:", style="Big.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(box, style="Hint.TLabel", text=f"The AI chose “{g[2]}”." if g[2] else "").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(2, 8))
        word = tk.StringVar(value=g[3] if g[3] else g[2])
        entry = ttk.Entry(box, textvariable=word, width=36)
        entry.grid(row=2, column=0, columnspan=4, sticky="ew")
        problem = tk.StringVar()
        ttk.Label(box, textvariable=problem, foreground="#dc2626").grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))

        def done(choice):
            g[3] = None if choice == g[2] else choice
            win.destroy()
            self.refresh(g[0][0])
            self.tell()

        def use():
            said = " ".join(word.get().split())
            if not said:
                return problem.set("Type a word, or press Just mute it.")
            try:
                profmute.use_words(self.app.path(self.app.words) or None)
            except SystemExit:    # the word list cannot be read: check against the built-in one
                profmute.RULES = profmute.parse_words(profmute.DEFAULT_WORDS, "built-in list")
            if profmute.find_hits([(n, n + 0.5, w, *profmute.norm(w)) for n, w in enumerate(said.split())]):
                return problem.set("That is on your word list: it would be muted again.")
            done(said)
        buttons = ttk.Frame(box)
        buttons.grid(row=4, column=0, columnspan=4, sticky="w", pady=(10, 0))
        for text, command, tip in (("Use this word", use, "It is said in the actor's voice in place of the swear."),
                                   ("Just mute it", lambda: done(""), "No word is said here: the swear is only muted."),
                                   ("Use the AI's word", lambda: done(g[2]), "Back to the word the AI chose."),
                                   ("Cancel", win.destroy, "Change nothing.")):
            b = ttk.Button(buttons, text=text, command=command)
            b.pack(side="left", padx=(0, 6))
            Tooltip(b, tip)
        entry.bind("<Return>", lambda e: use())
        win.bind("<Escape>", lambda e: win.destroy())
        self.app.title_bar(win)
        win.update_idletasks()
        x = self.win.winfo_rootx() + (self.win.winfo_width() - win.winfo_width()) // 2
        y = self.win.winfo_rooty() + (self.win.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        entry.focus_set()
        entry.select_range(0, "end")
        self.word_win = win

    # ---- finding
    def search(self):
        t, q = self.text, self.query.get().strip().lower()
        t.tag_remove("found", "1.0", "end")
        t.tag_remove("current", "1.0", "end")
        self.found, self.current = [], -1
        if len(q) >= 2:
            flat, owner = [], []          # the words as heard, lower case, and the word each letter belongs to
            for line in self.lines:
                for i in line:
                    word = self.words[i][2].lower()
                    flat.append(word + " ")
                    owner += [i] * (len(word) + 1)
                flat.append("\n")
                owner.append(None)
            flat = "".join(flat)
            at = flat.find(q)
            while at >= 0:
                hit = sorted({owner[k] for k in range(at, at + len(q)) if owner[k] is not None})
                if hit and (self.find_muted.get() or not any(self.muted(i) for i in hit)):
                    self.found.append(hit)
                    for i in hit:
                        t.tag_add("found", *t.tag_ranges(f"w{i}"))
                at = flat.find(q, at + 1)
        self.count.set(f"{len(self.found)} found" if q else "")
        if self.found:
            self.step(1)

    def step(self, direction):
        if not self.found:
            return
        self.current = (self.current + direction) % len(self.found)
        t = self.text
        t.tag_remove("current", "1.0", "end")
        hit = self.found[self.current]
        for i in hit:
            t.tag_add("current", *t.tag_ranges(f"w{i}"))
        t.see(t.tag_ranges(f"w{hit[0]}")[0])
        self.count.set(f"{self.current + 1} of {len(self.found)}")

    # ---- hearing a line
    def play(self, n):
        if not winsound:
            return
        line = self.lines[n]
        start, end = max(0.0, self.words[line[0]][0] - 0.4), self.words[line[-1]][1] + 0.4

        def work():
            out = os.path.join(tempfile.gettempdir(), "profmute-transcript-line.wav")
            r = subprocess.run([profmute.FFMPEG, "-v", "error", "-y", "-ss", f"{start:.2f}", "-i", self.job["movie"], "-t",
                                f"{end - start:.2f}", "-map", "0:a:0", "-ac", "1", "-ar", "22050", out],
                               capture_output=True, creationflags=NO_WINDOW)
            if r.returncode == 0:
                winsound.PlaySound(out, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        threading.Thread(target=work, daemon=True).start()

    # ---- done
    def picks(self):
        """The changes, as times: picked words that follow each other become one phrase."""
        mute, run = [], []
        for i in sorted(self.picked):
            if run and (i != run[-1] + 1 or self.words[i][0] - self.words[run[-1]][1] > 0.6):
                mute.append(run)
                run = []
            run.append(i)
        if run:
            mute.append(run)
        return {"mute": [[self.words[r[0]][0], self.words[r[-1]][1], " ".join(self.words[i][2] for i in r)] for r in mute],
                "keep": [[self.words[i][0], self.words[i][1], self.words[i][2]] for i in sorted(self.kept)],
                "say": [[g[4], g[5], g[1], g[3]] for g in self.says if g[3] is not None]}

    def finish(self):
        if winsound:
            winsound.PlaySound(None, winsound.SND_PURGE)
        self.data["picks"], self.data["transcript_done"] = self.picks(), True
        self.close()
        self.done(self.data)

    def close(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass


class App(ttk.Frame):
    def __init__(self, root):
        super().__init__(root, padding=12)
        self.root = root
        self.proc = None
        self.q = queue.Queue()   # from the worker threads: text, an exit code, or a ("kind", data) message
        self.auto_out = ""       # the output paths we filled in ourselves, so we know when to refresh them
        self.auto_srt = ""
        self.pending_cr = False  # a "\r" arrived: the next text overwrites the current line
        self.linebuf = ""        # script output not yet known to be text or a question
        self.cancelled = False
        self.jobs = []           # movies still to run; each {"cmd", "out", "title", "iid" (batch rows only)}
        self.job = None          # the one running now
        self.job_n = self.job_total = 0
        self.results = Counter()
        self.found = None        # "Found N spots" as reported by the current run
        self.writing = None      # the current output file, once the run has started writing it
        self.batch = {}          # batch list, movie rows: tree row id -> {"movie": Path, "srt": chosen subtitle
                                 # file or "", "on": ticked, "root": the added folder it came from (or None),
                                 # "side": the subtitle file found next to it when the folder was scanned}
        self.folders = {}        # batch list, folder rows: tree row id -> Path
        self.scanning = 0        # folders still being scanned
        self.popped = False      # the batch list has a window of its own
        self.ask_win = None      # the conflict pop-up, while one is open
        self.ask_info = {}       # and the question it shows
        self.later = None        # a three-round batch (listen, ask, write): its jobs, each with its saved analysis
        self.questions = []      # its question round: (job, "conflicts" | "unresolved", question) still to ask
        self.reviewing = None    # and the one asked now
        self.later_transcript = False   # its transcript round: on or not, the movies still to review, the window open
        self.transcripts, self.transcript_win = [], None
        self.question_n = self.question_total = 0
        self.model_rows = []

        settings = load_settings()
        for path, default in ((WORDS, profmute.DEFAULT_WORDS), (MODELS, profmute.DEFAULT_MODELS),
                              (VOICE_MODELS, profmute.DEFAULT_VOICE_MODELS)):
            if not path.exists():  # put the editable files where people will look for them
                try:
                    path.write_text(default, encoding="utf-8")
                except OSError:
                    pass

        self.movie = tk.StringVar()
        self.srt = tk.StringVar()
        self.log_dir = tk.StringVar(value=str(HERE / "log"))
        self.words = tk.StringVar(value=settings.get("words") if os.path.isfile(settings.get("words") or "") else str(WORDS))
        self.out = tk.StringVar()
        self.out_srt = tk.StringVar()
        self.batch_out = tk.StringVar()
        self.skip_done = tk.BooleanVar(value=True)
        self.batch_ask = tk.BooleanVar(value=bool(settings.get("batch_ask", False)))
        self.batch_later = tk.BooleanVar(value=bool(settings.get("batch_later", True)))
        self.own_folder = tk.BooleanVar(value=bool(settings.get("batch_own_folder", True)))
        self.log_beside = tk.BooleanVar(value=bool(settings.get("log_beside", True)))
        self.confirm = tk.BooleanVar(value=bool(settings.get("confirm", True)))
        self.ask_unresolved = tk.BooleanVar(value=bool(settings.get("ask_unresolved", True)))
        self.review_transcript = tk.BooleanVar(value=bool(settings.get("review_transcript", False)))
        self.fade = tk.BooleanVar(value=bool(settings.get("fade", True)))
        self.dialogue_only = tk.BooleanVar(value=bool(settings.get("dialogue_only", True)))
        self.front_check = tk.BooleanVar(value=bool(settings.get("front_check", True)))
        self.separate = tk.BooleanVar(value=bool(settings.get("separate", True)))
        self.speak = tk.BooleanVar(value=bool(settings.get("speak", False)))
        self.dry = tk.BooleanVar()
        self.dark = tk.BooleanVar(value=saved_dark())
        self.pad_before = tk.StringVar(value=f"{profmute.PAD_BEFORE:.2f}")
        self.pad_after = tk.StringVar(value=f"{profmute.PAD_AFTER:.2f}")
        self.status = tk.StringVar(value="Ready.")
        self.inputs = []

        # the tabs and settings above, the messages below, and a divider between them that can be dragged
        self.split = ttk.PanedWindow(self, orient="vertical")
        self.split.pack(fill="both", expand=True)
        self.split.bind("<B1-Motion>", self.keep_divider, add="+")
        self.split.bind("<ButtonRelease-1>", self.keep_divider, add="+")
        body = self.body = ttk.Frame(self.split)
        self.tabs = ttk.Notebook(body)
        self.tabs.grid(row=0, column=0, columnspan=3, sticky="nsew", pady=(0, 8))
        one = ttk.Frame(self.tabs, padding=10)
        many = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(one, text="One movie")
        self.tabs.add(many, text="Batch")

        # --- one movie
        one.columnconfigure(1, weight=1)
        self.row(one, 0, "Movie file", self.movie, self.browse_movie, tip=TIPS["movie"])
        self.row(one, 1, "Subtitle file (optional)", self.srt, self.browse_srt,
                 "Leave empty to use a .srt next to the movie, or the subtitles inside it.", tip=TIPS["srt"])
        self.out_widgets = self.row(one, 3, "Output file", self.out, self.browse_out, tip=TIPS["out"])
        self.out_widgets += self.row(one, 4, "Clean subtitle file", self.out_srt, self.browse_out_srt, tip=TIPS["out_srt"])

        # --- batch
        many.columnconfigure(1, weight=1)
        many.rowconfigure(0, weight=1)
        # the list and its buttons: a classic frame, because only those can become a window of their own
        self.list_part = tk.Frame(many, highlightthickness=0)
        self.list_part.grid(row=0, column=0, columnspan=3, sticky="nsew")
        buttons = ttk.Frame(self.list_part)
        buttons.pack(side="bottom", fill="x", pady=(6, 0))
        box = ttk.Frame(self.list_part)
        box.pack(side="top", fill="both", expand=True)
        columns = (("#0", "Movie", 300), ("folder", "Folder", 170), ("subs", "Subtitles", 170), ("status", "Status", 150))
        self.tree = ttk.Treeview(box, columns=[c[0] for c in columns[1:]], show="tree headings", height=9,
                                 selectmode="extended")
        for key, title, width in columns:
            self.tree.heading(key, text=title, anchor="w")
            self.tree.column(key, width=width, anchor="w", stretch=key in ("#0", "folder"))
        self.tree.bind("<Button-1>", self.tree_click)
        self.tree.bind("<space>", lambda e: self.toggle(self.tree.selection()) or "break")
        tree_scroll = ttk.Scrollbar(box, command=self.tree.yview)
        tree_scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        Tooltip(self.tree, TIPS["list"])
        for text, command, tip in (("Add files...", self.add_files, "add_files"), ("Add folder...", self.add_folder, "add_folder"),
                                   ("Tick all", lambda: self.tick_all(True), "tick_all"),
                                   ("Untick all", lambda: self.tick_all(False), "untick_all"),
                                   ("Set subtitle...", self.set_subtitle, "set_subtitle"),
                                   ("Remove", self.remove_selected, "remove"), ("Clear", self.clear_batch, "clear")):
            b = ttk.Button(buttons, text=text, command=command)
            b.pack(side="left", padx=(0, 6))
            Tooltip(b, TIPS[tip])
            self.inputs.append(b)
        self.pop_btn = ttk.Button(buttons, text="Pop out list", command=self.pop_list)
        self.pop_btn.pack(side="right")
        Tooltip(self.pop_btn, TIPS["pop_out"])
        self.list_away = ttk.Frame(many)   # stands in for the list while it has a window of its own
        ttk.Label(self.list_away, text="The list is open in a window of its own.").pack(side="left")
        back = ttk.Button(self.list_away, text="Put it back", command=self.dock_list)
        back.pack(side="left", padx=10)
        Tooltip(back, TIPS["dock"])
        self.out_widgets += self.row(many, 2, "Output folder", self.batch_out, self.browse_batch_out,
                                     "Leave empty to put each clean copy next to its own movie.", tip=TIPS["batch_out"])
        options = ttk.Frame(many)
        options.grid(row=4, column=1, columnspan=2, sticky="w", padx=8, pady=(4, 0))
        own = ttk.Checkbutton(options, text="Keep the folder layout in the output folder", variable=self.own_folder,
                              command=lambda: save_settings(batch_own_folder=self.own_folder.get()))
        skip = ttk.Checkbutton(options, text="Skip movies that already have a clean copy", variable=self.skip_done)
        ask = ttk.Checkbutton(options, text="Ask me about conflicts",
                              variable=self.batch_ask, command=lambda: save_settings(batch_ask=self.batch_ask.get()))
        later = ttk.Checkbutton(options, text="Listen to every movie first, then ask me everything at once",
                                variable=self.batch_later, command=lambda: save_settings(batch_later=self.batch_later.get()))
        own.grid(row=0, column=0, sticky="w", padx=(0, 28))
        skip.grid(row=0, column=1, sticky="w")
        ask.grid(row=1, column=0, sticky="w", padx=(0, 28), pady=(4, 0))
        later.grid(row=1, column=1, sticky="w", pady=(4, 0))
        for box, tip in ((own, OWN_FOLDER_TIP), (skip, SKIP_TIP), (ask, ASK_TIP), (later, LATER_TIP)):
            Tooltip(box, tip)
        self.inputs += [own, skip, ask, later]

        # --- shared by both tabs
        beside = ttk.Checkbutton(body, text="Put the log next to the clean copy", variable=self.log_beside,
                                 command=self.log_beside_changed)
        beside.grid(row=1, column=1, columnspan=2, sticky="w", padx=8, pady=(0, 2))
        Tooltip(beside, LOG_BESIDE_TIP)
        self.inputs.append(beside)
        self.log_widgets = self.row(body, 2, "Log folder", self.log_dir, self.browse_log_dir, tip=TIPS["log_dir"])

        words_label = ttk.Label(body, text="Word list")
        words_label.grid(row=3, column=0, sticky="w", pady=4)
        words_entry = ttk.Entry(body, textvariable=self.words)
        words_entry.grid(row=3, column=1, sticky="ew", padx=8)
        words_buttons = ttk.Frame(body)
        words_buttons.grid(row=3, column=2, sticky="ew")
        words_browse = ttk.Button(words_buttons, text="Browse...", command=self.browse_words)
        words_browse.pack(side="left")
        words_edit = ttk.Button(words_buttons, text="Edit", width=6, command=self.edit_words)
        words_edit.pack(side="left", padx=(6, 0))
        for w in (words_label, words_entry, words_browse):
            Tooltip(w, TIPS["words"])
        Tooltip(words_edit, TIPS["words_edit"])
        self.inputs += [words_entry, words_browse, words_edit]

        model_label = ttk.Label(body, text="Whisper model")
        model_label.grid(row=4, column=0, sticky="w", pady=4)
        self.model_box = ttk.Combobox(body, state="readonly")
        self.model_box.bind("<<ComboboxSelected>>", self.model_changed)
        self.model_box.grid(row=4, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        for w in (model_label, self.model_box):
            Tooltip(w, TIPS["model"])
        self.inputs.append(self.model_box)
        cached = settings.get("models") if isinstance(settings.get("models"), dict) else {}
        self.show_models([{"name": name, "note": note, **cached.get(name, {})} for name, note in profmute.load_models()],
                         settings.get("model"))

        voice_label = ttk.Label(body, text="Voice model")
        voice_label.grid(row=5, column=0, sticky="w", pady=4)
        self.voice_box = ttk.Combobox(body, state="readonly")
        self.voice_box.bind("<<ComboboxSelected>>", self.voice_changed)
        self.voice_box.grid(row=5, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        for w in (voice_label, self.voice_box):
            Tooltip(w, TIPS["voice_model"])
        self.inputs.append(self.voice_box)
        self.voice_rows = []
        cached = settings.get("voice_models") if isinstance(settings.get("voice_models"), dict) else {}
        self.show_voice_models([{"name": m[0], **cached.get(m[0], {})} for m in profmute.load_voice_models()],
                               settings.get("voice_model"))
        if not self.separate.get():
            self.voice_box.configure(state="disabled")

        pad_label = ttk.Label(body, text="Padding (seconds)")
        pad_label.grid(row=6, column=0, sticky="w", pady=4)
        Tooltip(pad_label, TIPS["padding"])
        pads = ttk.Frame(body)
        pads.grid(row=6, column=1, columnspan=2, sticky="w", padx=8)
        for text, var, tip in (("before the word", self.pad_before, "pad_before"), ("after the word", self.pad_after, "pad_after")):
            spin = ttk.Spinbox(pads, textvariable=var, from_=0.0, to=2.0, increment=0.05, width=6, format="%.2f")
            spin.pack(side="left")
            label = ttk.Label(pads, text=text)
            label.pack(side="left", padx=(4, 16))
            for w in (spin, label):
                Tooltip(w, TIPS[tip])
            self.inputs.append(spin)

        # the options, in two columns: how the words are found (left), how they are muted (right)
        boxes = ttk.Frame(body)
        boxes.grid(row=7, column=1, columnspan=2, sticky="w", padx=8, pady=(6, 0))
        remember = lambda key, var: (lambda: save_settings(**{key: var.get()}))
        options = [
            (0, 0, "Confirm each word with a second listen", self.confirm, remember("confirm", self.confirm), CONFIRM_TIP),
            (1, 0, "Let me hear and decide unresolved words", self.ask_unresolved,
             remember("ask_unresolved", self.ask_unresolved), UNRESOLVED_TIP),
            (2, 0, "Let me review the transcript before writing", self.review_transcript,
             remember("review_transcript", self.review_transcript), TRANSCRIPT_TIP),
            (3, 0, "Preview only: write the log, no video", self.dry, self.dry_changed, PREVIEW_TIP),
            (0, 1, "Fade in and out at each mute", self.fade, remember("fade", self.fade), FADE_TIP),
            (1, 1, "Mute only the dialogue channel (surround)", self.dialogue_only,
             remember("dialogue_only", self.dialogue_only), DIALOGUE_TIP),
            (2, 1, "Check the front left/right speakers too", self.front_check,
             remember("front_check", self.front_check), FRONT_TIP),
            (3, 1, "Remove only the voice with AI (keeps music)", self.separate, self.separate_changed, SEPARATE_TIP),
            (4, 1, "Speak a clean word in the actor's voice (AI)", self.speak, remember("speak", self.speak), SPEAK_TIP),
        ]
        for r, c, text, var, command, tip in options:
            box = ttk.Checkbutton(boxes, text=text, variable=var, command=command)
            box.grid(row=r, column=c, sticky="w", padx=(0, 36), pady=(0 if r == 0 else 4, 0))
            if var is self.speak:
                self.speak_box = box
                if not self.separate.get():   # speaking needs the voice removal
                    box.configure(state="disabled")
            Tooltip(box, tip)
            self.inputs.append(box)

        bar = ttk.Frame(body)
        bar.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(12, 6))
        self.start_btn = ttk.Button(bar, text="Start", command=self.start)
        self.start_btn.pack(side="left")
        self.cancel_btn = ttk.Button(bar, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=8)
        ttk.Label(bar, textvariable=self.status).pack(side="left", padx=8)
        self.dark_box = ttk.Checkbutton(bar, text="Dark mode", variable=self.dark, command=self.dark_changed)
        self.dark_box.pack(side="right")
        for w, tip in ((self.start_btn, "start"), (self.cancel_btn, "cancel"), (self.dark_box, "dark")):
            Tooltip(w, TIPS[tip])

        pane = ttk.Frame(self.split, padding=(0, 6, 0, 0))
        self.text = tk.Text(pane, height=10, wrap="word", state="disabled", font=("Consolas", 10))
        scroll = ttk.Scrollbar(pane, command=self.text.yview)
        scroll.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.configure(yscrollcommand=scroll.set)

        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)          # a taller window makes the batch list taller
        self.split.add(body, weight=3)
        self.split.add(pane, weight=1)
        self.show_log_box()
        self.movie.trace_add("write", self.movie_changed)
        self.out.trace_add("write", self.out_changed)

        self.style = ttk.Style(root)
        self.light_theme = self.style.theme_use()
        self.light_text = {k: self.text.cget(k) for k in ("background", "foreground", "insertbackground",
                           "selectbackground", "selectforeground", "relief", "highlightthickness")}
        self.light_bg = root.cget("background")
        self.apply_theme()

        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)
        threading.Thread(target=self.fetch_models, daemon=True).start()

    def row(self, parent, r, label, var, browse, hint=None, tip=None):
        name = ttk.Label(parent, text=label)
        name.grid(row=r, column=0, sticky="w", pady=4)
        entry = ttk.Entry(parent, textvariable=var)
        entry.grid(row=r, column=1, sticky="ew", padx=8)
        button = ttk.Button(parent, text="Browse...", command=browse)
        button.grid(row=r, column=2, sticky="ew")
        if tip:
            for w in (name, entry, button):
                Tooltip(w, tip)
        if hint:
            ttk.Label(parent, text=hint, style="Hint.TLabel").grid(row=r + 1, column=1, columnspan=2, sticky="w", padx=8)
        self.inputs += [entry, button]
        return [entry, button]

    @staticmethod
    def path(var):
        return var.get().strip().strip('"')

    @staticmethod
    def python():
        return str(Path(sys.executable).with_name("python.exe"))

    # ------------------------------------------------------------ light and dark

    def dark_changed(self):
        self.apply_theme()
        save_settings(dark=self.dark.get())

    def apply_theme(self):
        s, c = self.style, DARK
        if self.dark.get():
            s.theme_use("clam")  # the native Windows theme ignores colors; this one takes them
            s.configure(".", background=c["bg"], foreground=c["fg"], fieldbackground=c["field"],
                        bordercolor=c["border"], darkcolor=c["border"], lightcolor=c["border"],
                        troughcolor=c["bg"], insertcolor=c["fg"], arrowcolor=c["fg"],
                        selectbackground=c["accent"], selectforeground="#ffffff", focuscolor=c["accent"])
            s.map(".", foreground=[("disabled", c["disabled"])])
            s.configure("TButton", background=c["button"], padding=(10, 3))
            s.map("TButton", background=[("disabled", c["bg"]), ("pressed", c["border"]), ("active", c["hover"])])
            for w in ("TEntry", "TSpinbox"):
                s.map(w, fieldbackground=[("disabled", c["bg"])],
                      bordercolor=[("focus", c["accent"])], lightcolor=[("focus", c["accent"])])
            for w in ("TSpinbox", "TCombobox"):
                s.configure(w, background=c["button"])
                s.map(w, background=[("active", c["hover"])], arrowcolor=[("disabled", c["disabled"])])
            s.map("TCombobox", fieldbackground=[("disabled", c["bg"]), ("readonly", c["field"])],
                  selectbackground=[("readonly", c["field"])], selectforeground=[("readonly", c["fg"])])
            s.configure("TCheckbutton", indicatorbackground=c["field"], indicatorforeground="#ffffff")
            s.map("TCheckbutton", background=[("active", c["bg"])],
                  indicatorbackground=[("selected", c["accent"]), ("disabled", c["bg"])])
            s.configure("TScrollbar", background=c["button"], bordercolor=c["bg"])
            s.map("TScrollbar", background=[("disabled", c["bg"]), ("active", c["hover"])])
            s.configure("TNotebook", background=c["bg"], tabmargins=(2, 4, 2, 0))
            s.configure("TNotebook.Tab", background=c["button"], padding=(14, 4))
            s.map("TNotebook.Tab", background=[("selected", c["bg"]), ("active", c["hover"])],
                  lightcolor=[("selected", c["bg"])])
            s.configure("Treeview", background=c["field"], fieldbackground=c["field"])
            s.map("Treeview", background=[("selected", c["accent"])], foreground=[("selected", "#ffffff")])
            s.configure("Treeview.Heading", background=c["button"], relief="flat")
            s.map("Treeview.Heading", background=[("active", c["hover"])])
            s.configure("Hint.TLabel", foreground=c["muted"])
            self.text.configure(background=c["field"], foreground=c["fg"], insertbackground=c["fg"],
                                selectbackground=c["accent"], selectforeground="#ffffff",
                                relief="flat", highlightthickness=1,
                                highlightbackground=c["border"], highlightcolor=c["border"])
            self.root.configure(background=c["bg"])
            drop = dict(background=c["field"], foreground=c["fg"], selectbackground=c["accent"], selectforeground="#ffffff")
        else:
            s.theme_use(self.light_theme)
            s.configure("Hint.TLabel", foreground="gray40")
            self.text.configure(**self.light_text)
            self.root.configure(background=self.light_bg)
            drop = dict(background="SystemWindow", foreground="SystemWindowText",
                        selectbackground="SystemHighlight", selectforeground="SystemHighlightText")
        s.configure("Big.TLabel", font=("Segoe UI", 12, "bold"))
        # the batch list's checkboxes are pictures, drawn in this theme's colors and sized for the screen
        size = round(13 * self.root.winfo_fpixels("1i") / 96)
        s.configure("Treeview", rowheight=max(size + 8, font.nametofont("TkDefaultFont").metrics("linespace") + 6))
        self.boxes = box_images(size, *((c["muted"], c["field"], c["accent"]) if self.dark.get()
                                        else ("#767676", "#ffffff", "#0067c0")))
        self.show_boxes()
        for iid in self.batch:
            self.show_row(iid)
        self.list_part.configure(background=c["bg"] if self.dark.get() else self.light_bg)
        if self.popped:
            self.title_bar(self.list_part)
        # the model list that drops down is a plain listbox the themes do not reach
        for box in (self.model_box, self.voice_box):
            popdown = self.tk.call("ttk::combobox::PopdownWindow", box)
            self.tk.call(f"{popdown}.f.l", "configure", *(x for k, v in drop.items() for x in ("-" + k, v)))
        self.title_bar(self.root)

    def title_bar(self, window):
        """Ask Windows for a dark (or normal) title bar; harmless where that is not supported."""
        try:
            import ctypes
            window.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
            value = ctypes.c_int(1 if self.dark.get() else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)  # redraw the frame, nothing else
        except Exception:
            pass

    # ------------------------------------------------------------ models and word list

    def model(self):
        return self.model_rows[self.model_box.current()]["name"]

    def model_changed(self, _event=None):
        self.model_box.selection_clear()
        save_settings(model=self.model())

    def show_models(self, rows, selected=None):
        selected = selected or (self.model() if self.model_rows else None)
        names = [r["name"] for r in rows]
        self.model_rows = rows
        self.model_box.configure(values=[model_label(r) for r in rows])
        self.model_box.current(names.index(selected) if selected in names else 0)

    def fetch_models(self):
        """In a thread: ask the script which models are downloaded and how big they are (it knows; we do not)."""
        for option, kind, needed in (("--list-models", "models", ("name", "note")), ("--list-voice-models", "voice_models", ("name",))):
            try:
                r = subprocess.run([self.python(), str(SCRIPT), option], capture_output=True, text=True,
                                   cwd=HERE, creationflags=NO_WINDOW, timeout=120)
                rows = json.loads(r.stdout.strip().splitlines()[-1])
                if rows and all(all(k in row for k in needed) for row in rows):
                    self.q.put((kind, rows))
            except Exception:
                pass  # offline or anything else: the lists from the text files, with remembered sizes, stay

    def voice_model(self):
        return self.voice_rows[self.voice_box.current()]["name"] if self.voice_rows else None

    def voice_changed(self, _event=None):
        self.voice_box.selection_clear()
        save_settings(voice_model=self.voice_model())

    def show_voice_models(self, rows, selected=None):
        selected = selected or self.voice_model()
        names = [r["name"] for r in rows]
        self.voice_rows = rows
        self.voice_box.configure(values=[voice_label(r, i == 0) for i, r in enumerate(rows)])
        if rows:
            self.voice_box.current(names.index(selected) if selected in names else 0)

    def separate_changed(self):
        save_settings(separate=self.separate.get())
        self.voice_box.configure(state="readonly" if self.separate.get() and not self.proc else "disabled")
        self.speak_box.configure(state="normal" if self.separate.get() and not self.proc else "disabled")

    def browse_words(self):
        p = filedialog.askopenfilename(title="Choose the word list", filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
                                       initialdir=os.path.dirname(self.path(self.words)) or str(HERE))
        if p:
            self.words.set(os.path.normpath(p))

    def edit_words(self):
        p = self.path(self.words)
        if not os.path.isfile(p):
            return messagebox.showerror("ProfMute", f"This word list does not exist:\n{p}")
        os.startfile(p)

    # ------------------------------------------------------------ one movie: the boxes

    def start_dir(self, var):
        p = self.path(var) or self.path(self.movie)
        if not p:
            return str(HERE)
        return p if os.path.isdir(p) else os.path.dirname(p)

    def browse_movie(self):
        p = filedialog.askopenfilename(title="Choose the movie", filetypes=VIDEOS, initialdir=self.start_dir(self.movie))
        if p:
            self.movie.set(os.path.normpath(p))

    def browse_srt(self):
        p = filedialog.askopenfilename(title="Choose the subtitle file", filetypes=SUBS, initialdir=self.start_dir(self.srt))
        if p:
            self.srt.set(os.path.normpath(p))

    def browse_log_dir(self):
        current = self.path(self.log_dir)
        p = filedialog.askdirectory(title="Choose the folder for logs",
                                    initialdir=current if os.path.isdir(current) else str(HERE))
        if p:
            self.log_dir.set(os.path.normpath(p))

    def browse_out(self):
        current = self.path(self.out)
        p = filedialog.asksaveasfilename(title="Save the clean copy as", defaultextension=".mkv",
                                         filetypes=[("Matroska video", "*.mkv")],
                                         initialdir=self.start_dir(self.out),
                                         initialfile=os.path.basename(current))
        if p:
            self.out.set(os.path.normpath(p))

    def browse_out_srt(self):
        current = self.path(self.out_srt)
        p = filedialog.asksaveasfilename(title="Save the clean subtitles as", defaultextension=".srt",
                                         filetypes=[("Subtitle file", "*.srt")],
                                         initialdir=self.start_dir(self.out_srt if current else self.out),
                                         initialfile=os.path.basename(current))
        if p:
            self.out_srt.set(os.path.normpath(p))

    def movie_changed(self, *_):
        """Suggest <name>.clean.mkv next to the movie, unless the output box holds the user's own choice."""
        movie = self.path(self.movie)
        if movie and self.path(self.out) in ("", self.auto_out):
            p = Path(movie)
            self.auto_out = str(p.with_name(p.stem + ".clean.mkv"))
            self.out.set(self.auto_out)

    def out_changed(self, *_):
        """Suggest <output name>.en.srt next to the output file, the name Plex pairs with the video."""
        out = self.path(self.out)
        if out and self.path(self.out_srt) in ("", self.auto_srt):
            p = Path(out)
            self.auto_srt = str(p.with_name((p.stem if p.suffix.lower() == ".mkv" else p.name) + ".en.srt"))
            self.out_srt.set(self.auto_srt)

    def dry_changed(self):
        for w in self.out_widgets:
            w.configure(state="disabled" if self.dry.get() else "normal")

    def log_beside_changed(self):
        save_settings(log_beside=self.log_beside.get())
        self.show_log_box()

    def show_log_box(self):
        """The Log folder box is not used while each log goes next to its clean copy."""
        for w in self.log_widgets:
            w.configure(state="disabled" if self.log_beside.get() or self.proc else "normal")

    # ------------------------------------------------------------ batch: the list

    def add_files(self):
        picked = filedialog.askopenfilenames(title="Add movies (and subtitle files, if they are not next to them)",
                                             filetypes=[("Movies and subtitles", VIDEO_GLOB + " *.srt"), ("All files", "*.*")])
        self.batch_add([Path(os.path.normpath(p)) for p in picked])

    def add_folder(self):
        folder = filedialog.askdirectory(title="Add a folder of movies or shows, such as your Movies or TV folder",
                                         initialdir=load_settings().get("batch_folder") or None)
        if not folder:
            return
        folder = Path(os.path.normpath(folder))
        save_settings(batch_folder=str(folder.parent))
        self.scanning += 1
        self.status.set(f"Looking for movies in {folder} ...")
        self.root.configure(cursor="watch")
        # a big library on a network share takes a while to list: not in the window's own thread
        threading.Thread(target=lambda: self.q.put(("scanned", folder, scan_library(folder))), daemon=True).start()

    def scanned(self, folder, found):
        """A folder has been scanned: add it as a tree of its folders and movies, nothing ticked yet."""
        self.scanning -= 1
        if not self.scanning:
            self.root.configure(cursor="")
        known = {os.path.normcase(str(d["movie"])) for d in self.batch.values()}
        found = [(p, side) for p, side in found if os.path.normcase(str(p)) not in known]
        if not found:
            self.status.set("Ready.")
            return messagebox.showinfo("ProfMute", f"No movies found in:\n{folder}" + (
                "\n\nMovies that are in the list already are not added again." if known else ""))
        top = self.tree.insert("", "end", text=folder.name or str(folder), open=True, values=(str(folder), "", ""))
        self.folders[top] = folder
        rows = {Path("."): top}   # folder below the added one -> its row
        for p, side in found:
            iid = self.tree.insert(self.folder_row(rows, folder, p.parent.relative_to(folder)), "end")
            self.batch[iid] = {"movie": p, "srt": "", "on": False, "root": folder, "side": side}
            self.show_row(iid)
        self.show_boxes()
        self.status.set(f"Added {len(found)} movie(s) from {folder}. Tick the ones to clean.")

    def folder_row(self, rows, root, rel):
        if rel not in rows:
            rows[rel] = iid = self.tree.insert(self.folder_row(rows, root, rel.parent), "end", text=rel.name,
                                               values=("", "", ""))
            self.folders[iid] = root / rel
        return rows[rel]

    # ticking

    def files_under(self, iid=""):
        """The movie rows at or below a row ("" = the whole list), in list order."""
        if iid in self.batch:
            return [iid]
        return [f for child in self.tree.get_children(iid) for f in self.files_under(child)]

    def tree_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and self.tree.identify_element(event.x, event.y) == "image":   # the checkbox
            self.toggle([iid])
            return "break"   # a click on the box ticks; it does not change the selection

    def toggle(self, rows):
        """Tick the rows, or untick them if everything in them is ticked already."""
        files = [f for iid in rows for f in self.files_under(iid)]
        if files:
            self.tick(files, not all(self.batch[f]["on"] for f in files))

    def tick_all(self, on):
        self.tick(self.files_under(), on)

    def tick(self, files, on):
        if self.job:   # the batch running now was made from the ticks at Start
            return
        for f in files:
            self.batch[f]["on"] = on
        self.show_boxes()

    def show_boxes(self, iid=""):
        """Draw the checkboxes at and below a row. A folder's box shows whether all, some or none of the movies
        in it are ticked. -> that row's state"""
        if iid in self.batch:
            state = "on" if self.batch[iid]["on"] else "off"
        else:
            states = {self.show_boxes(child) for child in self.tree.get_children(iid)}
            state = states.pop() if len(states) == 1 else "part" if states else "off"
        if iid:
            self.tree.item(iid, image=self.boxes[state])
        return state

    def batch_add(self, paths):
        """Add movies to the list, ticked; a subtitle file is attached to the movie in the list with the same name."""
        known = {os.path.normcase(str(d["movie"])) for d in self.batch.values()}
        for p in paths:
            if p.suffix.lower() in VIDEO_EXT and os.path.normcase(str(p)) not in known:
                known.add(os.path.normcase(str(p)))
                self.batch[self.tree.insert("", "end")] = {"movie": p, "srt": "", "on": True, "root": None,
                                                          "side": profmute.sidecar_srt(p)}
        orphans = []
        for p in paths:
            if p.suffix.lower() != ".srt":
                continue
            rows = [d for d in self.batch.values() if srt_belongs_to(p, d["movie"])] if not is_our_output(p) else []
            longest = max((len(d["movie"].stem) for d in rows), default=0)   # Movie.Part2.en.srt is not Movie.mkv's
            rows = [d for d in rows if len(d["movie"].stem) == longest]
            for d in rows:
                d["srt"] = str(p)
            if not rows:
                orphans.append(p.name)
        for iid in self.batch:
            self.show_row(iid)
        if orphans:
            messagebox.showinfo("ProfMute", "No movie in the list has a matching name for:\n" + "\n".join(orphans) +
                                "\n\nAdd its movie first, or select a movie and use Set subtitle.")

    def show_row(self, iid, status=None):
        d = self.batch[iid]
        subs = Path(d["srt"]).name if d["srt"] else d["side"].name if d["side"] else "inside the movie, if any"
        if status is None:
            status = self.tree.set(iid, "status")
        folder = "" if self.tree.parent(iid) else str(d["movie"].parent)   # inside a folder row it says so already
        self.tree.item(iid, text=d["movie"].name, image=self.boxes["on" if d["on"] else "off"],
                       values=(folder, subs, status))

    def set_subtitle(self):
        rows = [iid for iid in self.tree.selection() if iid in self.batch]
        if not rows:
            return messagebox.showinfo("ProfMute", "Select a movie in the list first (not a folder).")
        p = filedialog.askopenfilename(title="Choose the subtitle file for the selected movie", filetypes=SUBS,
                                       initialdir=str(self.batch[rows[0]]["movie"].parent))
        if p:
            for iid in rows:
                self.batch[iid]["srt"] = os.path.normpath(p)
                self.show_row(iid)

    def remove_selected(self):
        self.tree.delete(*self.tree.selection())   # a folder goes with everything in it
        self.batch = {iid: d for iid, d in self.batch.items() if self.tree.exists(iid)}
        self.folders = {iid: p for iid, p in self.folders.items() if self.tree.exists(iid)}
        self.show_boxes()

    def clear_batch(self):
        self.tree.delete(*self.tree.get_children())
        self.batch.clear()
        self.folders.clear()

    # room for the list

    def keep_divider(self, _event=None):
        """The divider can be dragged, but not so high that it hides settings, nor so low that no messages show."""
        top, low = self.split.sashpos(0), self.body.winfo_reqheight()
        want = min(max(top, low), max(low, self.split.winfo_height() - 80))
        if want != top:
            self.split.sashpos(0, want)

    def pop_list(self):
        """Give the list and its buttons a window of their own."""
        part = self.list_part
        part.grid_forget()
        self.root.wm_manage(part)
        part.configure(padx=10, pady=10)
        wm = lambda *args: self.tk.call("wm", *args[:1], part, *args[1:])
        wm("title", "ProfMute - batch list")
        wm("protocol", "WM_DELETE_WINDOW", self.register(self.dock_list))
        wm("minsize", 600, 300)
        if ICON.is_file():
            wm("iconbitmap", str(ICON))
        saved = load_settings().get("list_geometry")
        if not (saved and fits_screen(self.root, saved)):
            r = self.root
            saved = f"{r.winfo_width()}x{int(r.winfo_screenheight() * 0.75)}+{r.winfo_x() + 40}+{max(0, r.winfo_y())}"
        wm("geometry", saved)
        self.list_away.grid(row=0, column=0, columnspan=3, sticky="nw", pady=(20, 0))
        self.pop_btn.configure(text="Put list back", command=self.dock_list)
        self.title_bar(part)
        self.popped = True

    def dock_list(self):
        """Back into the Batch tab."""
        if not self.popped:
            return
        part = self.list_part
        save_settings(list_geometry=self.tk.call("wm", "geometry", part))
        self.root.wm_forget(part)
        part.configure(padx=0, pady=0)
        self.list_away.grid_forget()
        part.grid(row=0, column=0, columnspan=3, sticky="nsew")
        self.pop_btn.configure(text="Pop out list", command=self.pop_list)
        self.popped = False

    def browse_batch_out(self):
        p = filedialog.askdirectory(title="Choose the folder for the clean copies", initialdir=self.path(self.batch_out) or str(HERE))
        if p:
            self.batch_out.set(os.path.normpath(p))

    # ------------------------------------------------------------ starting

    def ffmpeg_ready(self):
        """ffmpeg is a separate program. True when it is there; otherwise offer to install it and return False."""
        if profmute.find_tool("ffmpeg") and profmute.find_tool("ffprobe"):
            return True
        winget = shutil.which("winget")
        if winget and messagebox.askyesno("ProfMute", "ProfMute needs ffmpeg, a free video tool, and it is not installed "
                                          "on this PC.\n\nInstall it now with winget, the installer built into Windows?"):
            self.status.set("Installing ffmpeg... a console window shows the progress.")
            self.start_btn.configure(state="disabled")
            threading.Thread(target=self.install_ffmpeg, args=(winget,), daemon=True).start()
        elif not winget:
            messagebox.showinfo("ProfMute", profmute.FFMPEG_HELP)
        return False

    def install_ffmpeg(self, winget):
        try:
            subprocess.run([winget, "install", "--id", "Gyan.FFmpeg", "-e", "--accept-source-agreements",
                            "--accept-package-agreements"], creationflags=NEW_CONSOLE)
        except OSError:
            pass
        self.q.put(("ffmpeg", bool(profmute.find_tool("ffmpeg") and profmute.find_tool("ffprobe"))))

    def shared_args(self, log_box=True):
        """The script arguments both tabs share, or None after telling the user what is wrong.

        log_box=False leaves the log folder out: the batch then gives each movie its own.
        """
        log_dir, words = self.path(self.log_dir), self.path(self.words)
        if log_box and not log_dir:
            return messagebox.showerror("ProfMute", "Choose a folder for the logs.")
        if not os.path.isfile(words):
            return messagebox.showerror("ProfMute", f"This word list does not exist:\n{words}")
        try:
            pads = [float(v.get().replace(",", ".")) for v in (self.pad_before, self.pad_after)]
            if min(pads) < 0 or max(pads) > 2:
                raise ValueError
        except ValueError:
            return messagebox.showerror("ProfMute", "Padding must be a number of seconds between 0 and 2, like 0.30")
        if not self.ffmpeg_ready():
            return None
        save_settings(words=words)
        return (["--log-dir", log_dir] if log_box else []) + \
               ["--words", words, "--model", self.model(), "--pad-before", str(pads[0]),
                "--pad-after", str(pads[1])] + (["--confirm"] if self.confirm.get() else []) + \
               (["--unresolved", "ask"] if self.ask_unresolved.get() else []) + (["--dry"] if self.dry.get() else []) + \
               ([] if self.fade.get() else ["--no-fade"]) + ([] if self.dialogue_only.get() else ["--all-channels"]) + \
               ([] if self.front_check.get() else ["--no-front-check"]) + \
               (["--voice-model", self.voice_model()] if self.separate.get() and self.voice_model() else ["--no-separate"]) + \
               (["--speak"] if self.speak.get() and self.separate.get() else [])

    def command(self, movie):
        return [self.python(), "-u", str(SCRIPT), str(movie)]

    def start(self):
        if self.tabs.index("current") == 1:
            return self.start_batch()
        movie, srt, out, out_srt = (self.path(v) for v in (self.movie, self.srt, self.out, self.out_srt))
        dry = self.dry.get()
        if not os.path.isfile(movie):
            return messagebox.showerror("ProfMute", "Choose a movie file first." if not movie
                                        else f"This movie file does not exist:\n{movie}")
        if srt and not os.path.isfile(srt):
            return messagebox.showerror("ProfMute", f"This subtitle file does not exist:\n{srt}")
        if not dry:
            if not out:
                return messagebox.showerror("ProfMute", "Choose where to save the clean copy.")
            if not out.lower().endswith(".mkv"):
                out += ".mkv"
                self.out.set(out)
                out_srt = self.path(self.out_srt)  # its suggestion follows the output name
            if os.path.exists(out) and os.path.samefile(out, movie):
                return messagebox.showerror("ProfMute", "The output file is the movie itself.\n"
                                            "Pick a different name so the original stays untouched.")
            if out_srt and not out_srt.lower().endswith(".srt"):
                out_srt += ".srt"
                self.out_srt.set(out_srt)
            if out_srt and srt and os.path.exists(out_srt) and os.path.samefile(out_srt, srt):
                return messagebox.showerror("ProfMute", "The clean subtitle file is the subtitle file being read.\n"
                                            "Pick a different name so the original stays untouched.")
        beside = self.log_beside.get()
        shared = self.shared_args(log_box=not beside)
        if not shared:
            return
        if beside:   # next to the clean copy (in a preview: where it would go)
            shared += ["--log-dir", os.path.dirname(os.path.abspath(out or movie))]
        if not dry:
            existing = [p for p in (out, out_srt) if p and os.path.exists(p)]
            if existing and not messagebox.askyesno("ProfMute", (
                    "This file already exists:" if len(existing) == 1 else "These files already exist:")
                    + "\n" + "\n".join(existing) + "\n\nReplace?"):
                return

        cmd = self.command(movie) + shared + ["--conflicts", "ask"]
        if srt:
            cmd += ["--srt", srt]
        if not dry:
            cmd += ["--out", out] + (["--out-srt", out_srt] if out_srt else [])
        jobs = [{"cmd": cmd, "out": out, "title": os.path.basename(movie), "movie": movie}]
        self.later = None
        if not dry and self.review_transcript.get():   # listen, ask, show the transcript, then write
            self.in_rounds(jobs)
        self.run_jobs(jobs)

    def start_batch(self):
        if self.scanning:
            return messagebox.showinfo("ProfMute", "A folder is still being searched for movies. Start again when it "
                                       "is in the list.")
        if not self.batch:
            return messagebox.showerror("ProfMute", "Add at least one movie to the list first.")
        rows = [iid for iid in self.files_under() if self.batch[iid]["on"]]
        if not rows:
            return messagebox.showerror("ProfMute", "Tick at least one movie in the list first.")
        dry, out_dir = self.dry.get(), self.path(self.batch_out)
        own_folder, log_beside = self.own_folder.get(), self.log_beside.get()
        if own_folder and not out_dir:
            return messagebox.showerror("ProfMute", "Choose an output folder first.\n\n\"Keep the folder layout\" "
                                        "makes the folders inside the output folder.")
        shared = self.shared_args(log_box=not log_beside)
        if not shared:
            return
        shared += ["--conflicts", "ask" if self.batch_ask.get() else "auto"]
        jobs, skipped = [], 0
        for iid in rows:
            d = self.batch[iid]
            movie = d["movie"]
            folder = Path(out_dir) if out_dir else movie.parent
            if own_folder and d["root"] and movie.parent != d["root"]:   # TV\Show\Season 01\x -> Output\Show\Season 01\x
                folder = folder / movie.parent.relative_to(d["root"])
            elif own_folder:   # Output\Iron Man\Iron Man.clean.mkv (a folder name cannot end in a dot or a space)
                folder = folder / (movie.stem.rstrip(". ") or movie.stem)
            out = folder / (movie.stem + ".clean.mkv")
            if not movie.is_file():
                self.show_row(iid, "Movie file is missing")
            elif d["srt"] and not os.path.isfile(d["srt"]):
                self.show_row(iid, "Subtitle file is missing")
            elif not dry and self.skip_done.get() and out.exists():
                self.show_row(iid, "Skipped: clean copy exists")
            else:
                cmd = self.command(movie) + shared + (["--srt", d["srt"]] if d["srt"] else []) + \
                      (["--log-dir", str(out.parent)] if log_beside else [])
                jobs.append({"cmd": cmd if dry else cmd + ["--out", str(out)], "out": str(out),
                             "title": movie.name, "iid": iid, "movie": str(movie)})
                self.show_row(iid, "Waiting")
                continue
            skipped += 1
        if not dry:
            outs = [os.path.normcase(j["out"]) for j in jobs]
            if len(set(outs)) < len(outs):
                for j in jobs:
                    self.show_row(j["iid"], "")
                same = next(j["out"] for j in jobs if outs.count(os.path.normcase(j["out"])) > 1)
                return messagebox.showerror("ProfMute", "Two ticked movies have the same file name, so they would "
                                            f"write the same clean copy:\n{same}\n\nLeave the output folder empty, "
                                            "tick \"Keep the folder layout\", or untick one of them.")
            existing = [j["out"] for j in jobs if os.path.exists(j["out"])]
            if existing and not messagebox.askyesno("ProfMute", f"{len(existing)} clean copies already exist and will "
                                                    "be replaced:\n" + "\n".join(existing[:8]) +
                                                    ("\n..." if len(existing) > 8 else "") + "\n\nContinue?"):
                for j in jobs:
                    self.show_row(j["iid"], "")
                return
        if not jobs:
            return self.status.set(f"Nothing to do: all {skipped} movie(s) skipped.")
        # listen to every movie first, ask everything together, then write: three rounds (see LATER_TIP)
        self.later = None
        if not dry and (self.review_transcript.get() or
                        self.batch_later.get() and (self.batch_ask.get() or self.ask_unresolved.get())):
            self.in_rounds(jobs)
        self.run_jobs(jobs, skipped)

    def in_rounds(self, jobs):
        """Listen to every movie, then the questions and transcripts, then write (see LATER_TIP): each job gets
        its saved analysis, and the command for each round."""
        REVIEW.mkdir(exist_ok=True)
        prune_reviews()
        for j in jobs:
            path = str(review_file(j["movie"], j["out"]))
            j.update(review=path, round=1, write_cmd=j["cmd"] + ["--from-review", path], cmd=j["cmd"] + ["--review-file", path])
        self.later, self.later_transcript = jobs[:], self.review_transcript.get()

    # ------------------------------------------------------------ running

    def run_jobs(self, jobs, skipped=0, fresh=True):
        """fresh=False: the next round of the same batch (the messages and the counts so far are kept)."""
        if fresh:
            self.text.configure(state="normal")
            self.text.delete("1.0", "end")
            self.text.configure(state="disabled")
            self.results = Counter(skipped=skipped)
        self.jobs, self.job_n, self.job_total = list(jobs), 0, len(jobs)
        self.cancelled = False
        self.set_running(True)
        self.status.set("Starting...")
        self.next_job()

    def next_job(self):
        self.job = job = self.jobs.pop(0)
        self.job_n += 1
        self.writing, self.pending_cr, self.found, self.linebuf = None, False, None, ""
        if "iid" in job:
            self.write(f"{'' if self.job_n == 1 else chr(10)}===== [{self.job_n}/{self.job_total}] {job['title']} =====\n")
            self.show_row(job["iid"], {1: "Listening...", 3: "Writing..."}.get(job.get("round"), "Running..."))
            self.tree.see(job["iid"])
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        self.proc = subprocess.Popen(job["cmd"], cwd=HERE, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        threading.Thread(target=self.pump, args=(self.proc,), daemon=True).start()

    def pump(self, proc):
        """Runs in a thread: hand the process output, then its exit code, to the window."""
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while chunk := proc.stdout.read1(4096):
            self.q.put(decoder.decode(chunk))
        self.q.put(proc.wait())

    def poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                if isinstance(item, int):
                    self.finished(item)
                elif isinstance(item, str):
                    self.feed(item)
                elif item[0] == "models":
                    self.show_models(item[1])
                    save_settings(models={r["name"]: {"size": r.get("size"), "downloaded": r.get("downloaded")}
                                          for r in item[1]})
                elif item[0] == "voice_models":
                    self.show_voice_models(item[1])
                    save_settings(voice_models={r["name"]: {"size": r.get("size"), "downloaded": r.get("downloaded")}
                                                for r in item[1]})
                elif item[0] == "scanned":
                    self.scanned(item[1], item[2])
                elif item[0] == "ffmpeg":
                    self.start_btn.configure(state="normal")
                    self.status.set("ffmpeg is installed. Press Start again." if item[1] else "ffmpeg was not installed.")
                    if not item[1]:
                        messagebox.showinfo("ProfMute", profmute.FFMPEG_HELP)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def feed(self, text):
        """Output from the script: show it, except whole lines that are questions for the user."""
        self.linebuf += text
        while "\n" in self.linebuf:
            line, _, self.linebuf = self.linebuf.partition("\n")
            if line.lstrip("\r").startswith(profmute.ASK):
                self.ask(json.loads(line.lstrip("\r")[len(profmute.ASK):]))
            else:
                self.write(line + "\n")
        start = self.linebuf.lstrip("\r")[:len(profmute.ASK)]
        if start and not profmute.ASK.startswith(start):  # cannot become a question: show it now (progress counters)
            self.write(self.linebuf)
            self.linebuf = ""

    def write(self, text):
        t = self.text
        t.configure(state="normal")
        for part in re.split(r"([\r\n])", text):
            if part == "\r":
                self.pending_cr = True
            elif part == "\n":
                self.pending_cr = False
                t.insert("end", "\n")
            elif part:
                if self.pending_cr:  # progress counters rewrite their own line
                    t.delete("end-1c linestart", "end-1c")
                    self.pending_cr = False
                t.insert("end", part)
                if re.match(r"\d/\d ", part):
                    batch = f"[{self.job_n}/{self.job_total}] " if self.job and "iid" in self.job else ""
                    batch = {1: "Listening ", 3: "Writing "}.get((self.job or {}).get("round"), "") + batch
                    self.status.set(batch + part.strip())
                    if part.startswith("4/4") and self.job:
                        self.writing = self.job["out"]
                found = re.match(r"Found (\d+) spots", part)
                if found:
                    self.found = int(found.group(1))
        t.see("end")
        t.configure(state="disabled")

    # ------------------------------------------------------------ conflicts: the user decides

    def ask(self, info, movie=None, number=None):
        """Show a question about a conflict or an unresolved word: the script waits for the answer, or (in a
        batch's question round, with the movie's name and the question's number among all of them) it is saved."""
        self.ask_info = info
        unresolved = info.get("kind") == "unresolved"
        what = "unresolved word" if unresolved else "conflict"
        counted = f"question {number[0]} of {number[1]}" if number else f"{what} {info['n']} of {info['of']}"
        self.status.set(f"Waiting for you: {counted}")
        if winsound and (not number or number[0] == 1):   # in the question round: one beep at the start
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        win = self.ask_win = tk.Toplevel(self.root)
        win.title(f"ProfMute - {counted}")
        win.transient(self.root)
        win.resizable(False, False)
        if self.dark.get():
            win.configure(background=DARK["bg"])
        box = ttk.Frame(win, padding=18)
        box.pack(fill="both", expand=True)
        movie = movie or (self.job["title"] if self.job else "")
        if unresolved:
            headline = f"“{info['word']}” somewhere near {info['time'][:8]}"
            explanation = "The subtitles have this word, but Whisper did not hear it, so nothing is muted yet."
            facts = [("Movie", movie),
                     ("Subtitle line", f"{info['line']}   ({info['line_seconds']:.1f} seconds)"),
                     ("Whisper heard", info["heard"] or "(nothing there)"),
                     ("Best guess", f"{info['spot']}   ({info['spot_seconds']:.1f} seconds)")]
            plays = [("play_line", "▶  Play the line", "clip"), ("play_spot", "▶  Play the spot", "clip_spot")]
            choices = [("line", "Mute the whole line", "line"), ("spot", "Mute the estimated spot", "spot"),
                       ("leave_unresolved", "Leave it", "leave")]
            rest = ("leave_rest", "Leave this one and all the rest in this movie")
        else:
            headline = f"“{info['word']}” at {info['time'][:8]}"
            explanation = "Whisper heard this word, but the subtitles do not have it."
            facts = [("Movie", movie),
                     ("Whisper heard", f"{info['before']}  »{info['word']}«  {info['after']}".strip()),
                     ("Subtitles say", info["subtitles"] or "(nothing at that moment)")]
            if info.get("listens"):
                facts.append(("Second listens", info["listens"].capitalize()))
            plays = [("play", "▶  Play", "clip")]
            choices = [("mute", "Mute it", "mute"), ("leave", "Leave it", "leave")]
            rest = ("auto", "Decide the rest of this movie automatically")
        if info.get("previous"):   # back at a question answered before
            facts.append(("You answered", ANSWER_WORDS.get(info["previous"], info["previous"])))

        def button(parent, tip, text, command, enabled=True):
            b = ttk.Button(parent, text=text, command=command, state="normal" if enabled else "disabled")
            Tooltip(b, BUTTON_TIPS[tip])
            return b

        ttk.Label(box, text=headline, style="Big.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(box, text=explanation, style="Hint.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 12))
        for r, (label, value) in enumerate(facts, 2):
            ttk.Label(box, text=label).grid(row=r, column=0, sticky="nw", pady=3, padx=(0, 14))
            ttk.Label(box, text=value, wraplength=460, justify="left").grid(row=r, column=1, sticky="w", pady=3)
        listen = ttk.Frame(box)
        listen.grid(row=len(facts) + 2, column=0, columnspan=2, sticky="w", pady=(16, 0))
        for tip, text, clip in plays:
            button(listen, tip, text, lambda clip=clip: self.play_clip(clip),
                   bool(winsound and info.get(clip))).pack(side="left", padx=(0, 6))
        decide = ttk.Frame(box)
        decide.grid(row=len(facts) + 3, column=0, columnspan=2, sticky="w", pady=(10, 0))
        for tip, text, reply in choices:
            button(decide, tip, text, lambda reply=reply: self.answer(reply)).pack(side="left", padx=(0, 6))
        bottom = ttk.Frame(box)
        bottom.grid(row=len(facts) + 4, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        button(bottom, rest[0], rest[1], lambda: self.answer("auto")).pack(side="left")
        button(bottom, "back", "◀  Back", lambda: self.answer("back"), bool(info.get("can_go_back"))).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", lambda: self.answer("auto"))
        self.title_bar(win)
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        win.lift()
        win.focus_force()

    def play_clip(self, which="clip"):
        clip = self.ask_info.get(which)
        if winsound and clip and os.path.isfile(clip):
            winsound.PlaySound(clip, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)

    def close_ask(self):
        if winsound:
            winsound.PlaySound(None, winsound.SND_PURGE)   # stop playing: the script deletes the clip next
        if self.ask_win:
            self.ask_win.destroy()
            self.ask_win = None

    def answer(self, reply):
        info = self.ask_info
        self.close_ask()
        if reply == "back":
            self.write("    Back to the question before\n")
        elif info.get("kind") == "unresolved":
            said = {"line": "whole line muted", "spot": "estimated spot muted", "leave": "left in",
                    "auto": "left in, and so are the rest"}[reply]
            self.write(f"    Unresolved {info['n']}/{info['of']} at {info['time']} \"{info['word']}\": {said}\n")
        else:
            said = {"mute": "muted", "leave": "left in", "auto": "three listens decide this one and the rest"}[reply]
            self.write(f"    Conflict {info['n']}/{info['of']} at {info['time']} \"{info['word']}\": {said}\n")
        if self.reviewing:
            return self.review_back() if reply == "back" else self.save_answer(reply)
        self.status.set("Working...")
        if self.proc:
            try:
                self.proc.stdin.write((reply + "\n").encode())
                self.proc.stdin.flush()
            except OSError:
                pass  # the run ended meanwhile

    # ------------------------------------------------------------ a batch's question round (see LATER_TIP)

    def start_review(self):
        """Every movie has been listened to: all their open questions, one after another."""
        self.questions = []
        for j in self.later:
            data = read_review(j["review"]) if j.get("listened") else None
            if data:
                self.questions += [(j, part, info) for part, info in open_questions(data)]
        self.question_n, self.question_total = 0, len(self.questions)
        self.review_history, self.review_previous = [], {}   # answered: (question, answer, answered with it, number)
        if not self.questions:
            return self.transcript_round()
        movies = len({id(q[0]) for q in self.questions})
        self.write(f"\n===== {self.question_total} question(s) about {movies} movie(s): waiting for you =====\n")
        for j in {id(q[0]): q[0] for q in self.questions}.values():
            self.job_row(j, "Waiting for your answers")
        self.set_running(True)
        self.next_question()

    def next_question(self):
        job, part, info = self.reviewing = self.questions.pop(0)
        self.question_n += 1
        info = dict(info, can_go_back=bool(self.review_history), previous=self.review_previous.get((id(job), part, info["n"])))
        self.ask(info, movie=job["title"], number=(self.question_n, self.question_total))

    def save_answer(self, reply):
        """Kept in the movie's saved analysis right away: stopping now loses nothing."""
        job, part, info = self.reviewing
        data = read_review(job["review"])
        if data is not None:
            data["answers"][part][str(info["n"])] = reply
            profmute.save_review(job["review"], data)
        gone = []
        if reply == "auto":   # the rest of this movie's questions of this kind are answered by that too
            gone = [q for q in self.questions if q[0] is job and q[1] == part]
            self.questions = [q for q in self.questions if q not in gone]
            self.question_n += len(gone)
        self.review_history.append((self.reviewing, reply, gone, self.question_n - len(gone)))
        if not any(q[0] is job for q in self.questions):
            self.job_row(job, "Answered")
        if self.questions:
            return self.next_question()
        self.transcript_round()

    def review_back(self):
        """Back to the question answered last: its saved answer is taken back, and so are the ones it answered
        along with it ('decide the rest'), which come back in turn."""
        (job, part, info), reply, gone, number = self.review_history.pop()
        data = read_review(job["review"])
        if data is not None:
            data["answers"][part].pop(str(info["n"]), None)
            profmute.save_review(job["review"], data)
        self.review_previous[(id(job), part, info["n"])] = reply
        self.questions = [(job, part, info)] + gone + [self.reviewing] + self.questions
        self.question_n = number - 1
        self.job_row(job, "Waiting for your answers")
        self.next_question()

    def transcript_round(self):
        """After the questions: each movie's transcript, to check and change before it is written."""
        self.reviewing = None
        self.transcripts = [j for j in self.later if j.get("listened") and self.later_transcript
                            and not (read_review(j["review"]) or {}).get("transcript_done")]
        if self.transcripts:
            self.write(f"\n===== {len(self.transcripts)} transcript(s) to review: waiting for you =====\n")
            for j in self.transcripts:
                self.job_row(j, "Transcript to review")
            self.set_running(True)
        self.next_transcript()

    def next_transcript(self):
        if not self.transcripts:
            return self.write_round()
        job = self.transcripts.pop(0)
        data = read_review(job["review"])
        if data is None:
            return self.next_transcript()
        self.status.set(f"Waiting for you: the transcript of {job['title']}")
        self.job_row(job, "Reviewing the transcript")
        self.transcript_win = Transcript(self, job, data, lambda data, job=job: self.transcript_done(job, data))

    def transcript_done(self, job, data):
        self.transcript_win = None
        profmute.save_review(job["review"], data)
        picks = data.get("picks") or {}
        self.write(f"    Transcript of {job['title']}: {len(picks.get('mute', []))} muted by you, "
                   f"{len(picks.get('keep', []))} kept by you, {len(picks.get('say', []))} word(s) chosen by you\n")
        self.job_row(job, "Reviewed")
        self.next_transcript()

    def write_round(self):
        """The last round: every clean copy, written with the answers."""
        self.reviewing = None
        jobs = [dict(j, cmd=j["write_cmd"], round=3) for j in self.later if j.get("listened")]
        self.later = None
        if not jobs:
            return self.batch_done()
        self.write("\n===== Writing the clean copies =====\n")
        self.run_jobs(jobs, fresh=False)

    def stop_review(self):
        """Cancel during the question round or the transcripts: the answers and reviewed transcripts so far stay
        saved (a transcript open now is not)."""
        self.close_ask()
        for j in {id(q[0]): q[0] for q in ([self.reviewing] if self.reviewing else []) + self.questions}.values():
            self.job_row(j, "Waiting for your answers")
        if self.transcript_win:
            self.job_row(self.transcript_win.job, "Transcript to review")
            self.transcript_win.close()
        for j in self.transcripts:
            self.job_row(j, "Transcript to review")
        self.reviewing, self.questions, self.later, self.transcripts, self.transcript_win = None, [], None, [], None
        again = "the same batch" if self.tabs.index("current") == 1 else "again"
        self.status.set(f"Stopped. Your answers so far are saved: start {again} to carry on.")
        self.write(f"\n===== {self.status.get()} =====\n")
        self.set_running(False)

    def job_row(self, job, status):
        """A batch movie's row in the list; a single movie has none."""
        if job.get("iid"):
            self.show_row(job["iid"], status)

    # ------------------------------------------------------------ finishing

    def finished(self, code):
        self.proc = None
        self.close_ask()
        if self.linebuf:
            self.write(self.linebuf)
            self.linebuf = ""
        job, batch = self.job, "iid" in self.job
        if self.cancelled:
            outcome, row = "cancelled", "Cancelled"
            if self.writing and os.path.exists(self.writing):
                os.remove(self.writing)
                self.write(f"\nCancelled. Removed the unfinished output file:\n{self.writing}\n")
            else:
                self.write("\nCancelled.\n")
        elif code != 0:
            outcome, row = "failed", "Failed - see the messages"
            if self.writing and os.path.exists(self.writing):  # a broken file must not pass for a clean copy later
                os.remove(self.writing)
                self.write(f"\nRemoved the unfinished output file:\n{self.writing}\n")
        elif self.dry.get():
            outcome, row = "done", f"Preview: {self.found} found"
        elif self.found == 0:
            outcome, row = "done", "Nothing to mute"
        else:
            outcome, row = "done", f"Done: {self.found} muted"
        listening = job.get("round") == 1
        if listening and outcome == "done":   # the first round of three: listened to, written later
            data = read_review(job["review"])
            job["listened"] = data is not None
            asks = len(open_questions(data)) if data else 0
            row = f"Listened: {asks} question(s)" if asks else "Listened: no questions"
        else:
            self.results[outcome] += 1
        if batch:
            self.show_row(job["iid"], row)
            if self.jobs and not self.cancelled:
                return self.next_job()
            for waiting in self.jobs:
                self.show_row(waiting["iid"], "Not run")
        if listening and not self.cancelled and self.later and (batch or outcome == "done"):   # on to the questions
            self.jobs, self.job = [], None
            return self.start_review()
        if batch:
            return self.batch_done()
        self.status.set({"cancelled": "Cancelled.", "done": "Done.",
                         "failed": "Something went wrong - see the messages below."}[outcome])
        self.jobs, self.job = [], None
        self.set_running(False)
        threading.Thread(target=self.fetch_models, daemon=True).start()   # a model may have been downloaded just now

    def batch_done(self):
        r = self.results
        summary = f"{r['done']} done, {r['failed']} failed, {r['skipped']} skipped" + \
                  (f", {len(self.jobs)} not run" if self.jobs else "")
        self.status.set(("Batch cancelled: " if self.cancelled else "Batch finished: ") + summary + ".")
        self.write(f"\n===== {self.status.get()} =====\n")
        self.jobs, self.job, self.later = [], None, None
        self.set_running(False)
        threading.Thread(target=self.fetch_models, daemon=True).start()   # a model may have been downloaded just now

    def set_running(self, running):
        for w in self.inputs:
            w.configure(state="disabled" if running else "readonly" if w in (self.model_box, self.voice_box) else "normal")
        if not running and not self.separate.get():
            self.voice_box.configure(state="disabled")
            self.speak_box.configure(state="disabled")
        if not running:
            self.dry_changed()
            self.show_log_box()
        other = 1 - self.tabs.index("current")   # no switching tabs mid-run
        self.tabs.tab(other, state="disabled" if running else "normal")
        self.start_btn.configure(state="disabled" if running else "normal")
        self.cancel_btn.configure(state="normal" if running else "disabled")

    def cancel(self):
        if self.reviewing or self.transcript_win:
            return self.stop_review()
        if self.proc:
            self.cancelled = True
            self.status.set("Stopping...")
            # /T also stops the ffmpeg that profmute.py may have started
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                           capture_output=True, creationflags=NO_WINDOW)

    def close(self):
        if self.proc:
            if not messagebox.askyesno("ProfMute", "A movie is still being processed.\n\nStop it and close?"):
                return
            self.cancel()
            self.proc.wait()
            if self.writing and os.path.exists(self.writing):
                os.remove(self.writing)
        self.close_ask()
        self.remember_layout()
        self.root.destroy()

    def remember_layout(self):
        """The window's size and place, the divider and the list's own window, for the next start."""
        zoomed = self.root.state() == "zoomed"
        layout = dict(zoomed=zoomed, divider=self.split.sashpos(0))
        if self.root.state() == "normal":
            layout["window"] = self.root.geometry()
        if self.popped:
            layout["list_geometry"] = self.tk.call("wm", "geometry", self.list_part)
        save_settings(**layout)

    def restore_layout(self):
        s = load_settings()
        if fits_screen(self.root, s.get("window")):
            self.root.geometry(s["window"])
        if s.get("zoomed"):
            self.root.state("zoomed")
        if isinstance(s.get("divider"), int):
            self.root.update()   # the window at its full size first, or the divider is fitted into a smaller one
            self.split.sashpos(0, s["divider"])
            self.keep_divider()


def main():
    try:  # crisp text on high-DPI screens, and our own taskbar button instead of Python's
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ProfMute")
    except Exception:
        pass
    root = tk.Tk()
    root.title(f"ProfMute {profmute.__version__}")
    root.minsize(860, 900)
    if ICON.is_file():
        root.iconbitmap(default=str(ICON))
    app = App(root)
    app.pack(fill="both", expand=True)
    app.restore_layout()
    root.mainloop()


if __name__ == "__main__":
    main()
