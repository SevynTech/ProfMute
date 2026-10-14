"""profmute_gui - a small window for profmute.py.

Start it by double-clicking ProfMute.exe (a small launcher, see launcher\\ProfMute.cs), or:
uv run python profmute_gui.py
It runs profmute.py as a separate process (one per movie) and shows its output, so everything the
command line version does applies here too. The word list (words.txt) and the model list
(models.txt) sit next to this file and are meant to be edited.
"""
import codecs, json, os, queue, re, shutil, subprocess, sys, threading
import tkinter as tk
from collections import Counter
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

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
           "On: the batch stops at each one, plays a sound and lets you decide.\n"
           "Off: the batch never waits for you. Three listens decide, and the word is muted only if "
           "two of them hear it in the same place.")
UNRESOLVED_TIP = ("An unresolved word is one the subtitles have but Whisper never heard, even after "
                  "listening to that line again. ProfMute knows which subtitle line it is in, but not exactly when it is said.\n\n"
                  "On: ProfMute plays a sound and shows you each one. You can play the line, then mute the whole "
                  "line, mute only its best guess at the spot, or leave it. In a batch, this pauses the batch.\n"
                  "Off: nothing is muted. The lines are listed in the log under UNRESOLVED for you to check by ear.")
OWN_FOLDER_TIP = ("On: inside the output folder, each movie gets a folder named after it, holding its clean copy "
                  "and its clean subtitles:\n\n"
                  "     Output folder\\Iron Man\\Iron Man.clean.mkv\n\n"
                  "Off: every clean copy goes straight into the output folder.\n\n"
                  "Needs an output folder.")
LOG_BESIDE_TIP = ("The log lists every spot that was muted, with its time, plus the conflicts and unresolved words.\n\n"
                  "On: each movie's log is saved in the same folder as its clean copy.\n"
                  "Off: all logs go into the Log folder below, which starts as a \"log\" folder next to ProfMute.")
TIPS = {
    "movie": "The movie to clean. It is only read, never changed.",
    "srt": "Subtitles for this movie (a .srt file). They double-check what Whisper hears, and the clean subtitle "
           "file is made from them.\n\nLeave empty and ProfMute uses a .srt next to the movie with the same name, "
           "or else the English subtitles inside the movie file.",
    "out": "Where the clean copy is saved: the movie with the words on your list muted.\n\n"
           "Fills itself in as <movie name>.clean.mkv next to the movie. It is always an .mkv file.",
    "out_srt": "Where the clean subtitles are saved: the same subtitles with the words on your list deleted.\n\n"
               "Fills itself in next to the clean copy, under the name media players pair with it. "
               "Only written when the movie has subtitles.",
    "list": "The movies to clean, done one after another from the top. \"Subtitles\" shows which subtitles "
            "each one will use, \"Status\" how it went.",
    "add_files": "Add movies to the list. You can pick .srt files here too: each one is given to the movie "
                 "in the list that has the same name.",
    "add_folder": "Add every movie in a folder and in all the folders inside it. Clean copies made earlier are left out.",
    "set_subtitle": "Choose a subtitle file by hand for the movie selected in the list.",
    "remove": "Take the selected movies off the list. Nothing is deleted from your disk.",
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
    "start": "Clean the movie on the One movie tab, or every movie in the Batch list, whichever tab is showing.",
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
}


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
        self.batch = {}          # batch list: tree row id -> {"movie": Path, "srt": chosen subtitle file or ""}
        self.ask_win = None      # the conflict pop-up, while one is open
        self.ask_info = {}       # and the question it shows
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
        self.own_folder = tk.BooleanVar(value=bool(settings.get("batch_own_folder", False)))
        self.log_beside = tk.BooleanVar(value=bool(settings.get("log_beside", True)))
        self.confirm = tk.BooleanVar(value=bool(settings.get("confirm", False)))
        self.ask_unresolved = tk.BooleanVar(value=bool(settings.get("ask_unresolved", False)))
        self.fade = tk.BooleanVar(value=bool(settings.get("fade", True)))
        self.dialogue_only = tk.BooleanVar(value=bool(settings.get("dialogue_only", True)))
        self.front_check = tk.BooleanVar(value=bool(settings.get("front_check", True)))
        self.separate = tk.BooleanVar(value=bool(settings.get("separate", True)))
        self.dry = tk.BooleanVar()
        self.dark = tk.BooleanVar(value=saved_dark())
        self.pad_before = tk.StringVar(value=f"{profmute.PAD_BEFORE:.2f}")
        self.pad_after = tk.StringVar(value=f"{profmute.PAD_AFTER:.2f}")
        self.status = tk.StringVar(value="Ready.")
        self.inputs = []

        self.tabs = ttk.Notebook(self)
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
        box = ttk.Frame(many)
        box.grid(row=0, column=0, columnspan=3, sticky="nsew")
        columns = (("movie", "Movie", 250), ("folder", "Folder", 210), ("subs", "Subtitles", 170), ("status", "Status", 150))
        self.tree = ttk.Treeview(box, columns=[c[0] for c in columns], show="headings", height=6, selectmode="extended")
        for key, title, width in columns:
            self.tree.heading(key, text=title, anchor="w")
            self.tree.column(key, width=width, anchor="w", stretch=key in ("movie", "folder"))
        tree_scroll = ttk.Scrollbar(box, command=self.tree.yview)
        tree_scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        Tooltip(self.tree, TIPS["list"])
        buttons = ttk.Frame(many)
        buttons.grid(row=1, column=0, columnspan=3, sticky="w", pady=6)
        for text, command, tip in (("Add files...", self.add_files, "add_files"), ("Add folder...", self.add_folder, "add_folder"),
                                   ("Set subtitle...", self.set_subtitle, "set_subtitle"),
                                   ("Remove", self.remove_selected, "remove"), ("Clear", self.clear_batch, "clear")):
            b = ttk.Button(buttons, text=text, command=command)
            b.pack(side="left", padx=(0, 6))
            Tooltip(b, TIPS[tip])
            self.inputs.append(b)
        self.out_widgets += self.row(many, 2, "Output folder", self.batch_out, self.browse_batch_out,
                                     "Leave empty to put each clean copy next to its own movie.", tip=TIPS["batch_out"])
        options = ttk.Frame(many)
        options.grid(row=4, column=1, columnspan=2, sticky="w", padx=8, pady=(4, 0))
        own = ttk.Checkbutton(options, text="Give each movie its own folder in the output folder", variable=self.own_folder,
                              command=lambda: save_settings(batch_own_folder=self.own_folder.get()))
        skip = ttk.Checkbutton(options, text="Skip movies that already have a clean copy", variable=self.skip_done)
        ask = ttk.Checkbutton(options, text="Pause and ask me about conflicts",
                              variable=self.batch_ask, command=lambda: save_settings(batch_ask=self.batch_ask.get()))
        own.grid(row=0, column=0, sticky="w", padx=(0, 28))
        skip.grid(row=0, column=1, sticky="w")
        ask.grid(row=1, column=0, sticky="w", padx=(0, 28), pady=(4, 0))
        for box, tip in ((own, OWN_FOLDER_TIP), (skip, SKIP_TIP), (ask, ASK_TIP)):
            Tooltip(box, tip)
        self.inputs += [own, skip, ask]

        # --- shared by both tabs
        beside = ttk.Checkbutton(self, text="Put the log next to the clean copy", variable=self.log_beside,
                                 command=self.log_beside_changed)
        beside.grid(row=1, column=1, columnspan=2, sticky="w", padx=8, pady=(0, 2))
        Tooltip(beside, LOG_BESIDE_TIP)
        self.inputs.append(beside)
        self.log_widgets = self.row(self, 2, "Log folder", self.log_dir, self.browse_log_dir, tip=TIPS["log_dir"])

        words_label = ttk.Label(self, text="Word list")
        words_label.grid(row=3, column=0, sticky="w", pady=4)
        words_entry = ttk.Entry(self, textvariable=self.words)
        words_entry.grid(row=3, column=1, sticky="ew", padx=8)
        words_buttons = ttk.Frame(self)
        words_buttons.grid(row=3, column=2, sticky="ew")
        words_browse = ttk.Button(words_buttons, text="Browse...", command=self.browse_words)
        words_browse.pack(side="left")
        words_edit = ttk.Button(words_buttons, text="Edit", width=6, command=self.edit_words)
        words_edit.pack(side="left", padx=(6, 0))
        for w in (words_label, words_entry, words_browse):
            Tooltip(w, TIPS["words"])
        Tooltip(words_edit, TIPS["words_edit"])
        self.inputs += [words_entry, words_browse, words_edit]

        model_label = ttk.Label(self, text="Whisper model")
        model_label.grid(row=4, column=0, sticky="w", pady=4)
        self.model_box = ttk.Combobox(self, state="readonly")
        self.model_box.bind("<<ComboboxSelected>>", self.model_changed)
        self.model_box.grid(row=4, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        for w in (model_label, self.model_box):
            Tooltip(w, TIPS["model"])
        self.inputs.append(self.model_box)
        cached = settings.get("models") if isinstance(settings.get("models"), dict) else {}
        self.show_models([{"name": name, "note": note, **cached.get(name, {})} for name, note in profmute.load_models()],
                         settings.get("model"))

        voice_label = ttk.Label(self, text="Voice model")
        voice_label.grid(row=5, column=0, sticky="w", pady=4)
        self.voice_box = ttk.Combobox(self, state="readonly")
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

        pad_label = ttk.Label(self, text="Padding (seconds)")
        pad_label.grid(row=6, column=0, sticky="w", pady=4)
        Tooltip(pad_label, TIPS["padding"])
        pads = ttk.Frame(self)
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
        boxes = ttk.Frame(self)
        boxes.grid(row=7, column=1, columnspan=2, sticky="w", padx=8, pady=(6, 0))
        remember = lambda key, var: (lambda: save_settings(**{key: var.get()}))
        options = [
            (0, 0, "Confirm each word with a second listen", self.confirm, remember("confirm", self.confirm), CONFIRM_TIP),
            (1, 0, "Let me hear and decide unresolved words", self.ask_unresolved,
             remember("ask_unresolved", self.ask_unresolved), UNRESOLVED_TIP),
            (2, 0, "Preview only: write the log, no video", self.dry, self.dry_changed, PREVIEW_TIP),
            (0, 1, "Fade in and out at each mute", self.fade, remember("fade", self.fade), FADE_TIP),
            (1, 1, "Mute only the dialogue channel (surround)", self.dialogue_only,
             remember("dialogue_only", self.dialogue_only), DIALOGUE_TIP),
            (2, 1, "Check the front left/right speakers too", self.front_check,
             remember("front_check", self.front_check), FRONT_TIP),
            (3, 1, "Remove only the voice with AI (keeps music)", self.separate, self.separate_changed, SEPARATE_TIP),
        ]
        for r, c, text, var, command, tip in options:
            box = ttk.Checkbutton(boxes, text=text, variable=var, command=command)
            box.grid(row=r, column=c, sticky="w", padx=(0, 36), pady=(0 if r == 0 else 4, 0))
            Tooltip(box, tip)
            self.inputs.append(box)

        bar = ttk.Frame(self)
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

        pane = ttk.Frame(self)
        pane.grid(row=9, column=0, columnspan=3, sticky="nsew")
        self.text = tk.Text(pane, height=10, wrap="word", state="disabled", font=("Consolas", 10))
        scroll = ttk.Scrollbar(pane, command=self.text.yview)
        scroll.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.configure(yscrollcommand=scroll.set)

        self.columnconfigure(1, weight=1)
        self.rowconfigure(9, weight=1)
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
        folder = filedialog.askdirectory(title="Add every movie in a folder and its subfolders")
        if folder:
            movies = scan_folder(os.path.normpath(folder))
            if not movies:
                return messagebox.showinfo("ProfMute", f"No movies found in:\n{os.path.normpath(folder)}")
            self.batch_add(movies)

    def batch_add(self, paths):
        """Add movies to the list; a subtitle file is attached to the movie in the list with the same name."""
        known = {os.path.normcase(str(d["movie"])) for d in self.batch.values()}
        for p in paths:
            if p.suffix.lower() in VIDEO_EXT and os.path.normcase(str(p)) not in known:
                known.add(os.path.normcase(str(p)))
                self.batch[self.tree.insert("", "end")] = {"movie": p, "srt": ""}
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
        side = profmute.sidecar_srt(d["movie"])
        subs = Path(d["srt"]).name if d["srt"] else side.name if side else "inside the movie, if any"
        if status is None:
            status = self.tree.set(iid, "status")
        self.tree.item(iid, values=(d["movie"].name, str(d["movie"].parent), subs, status))

    def set_subtitle(self):
        rows = self.tree.selection()
        if not rows:
            return messagebox.showinfo("ProfMute", "Select a movie in the list first.")
        p = filedialog.askopenfilename(title="Choose the subtitle file for the selected movie", filetypes=SUBS,
                                       initialdir=str(self.batch[rows[0]]["movie"].parent))
        if p:
            for iid in rows:
                self.batch[iid]["srt"] = os.path.normpath(p)
                self.show_row(iid)

    def remove_selected(self):
        for iid in self.tree.selection():
            self.tree.delete(iid)
            del self.batch[iid]

    def clear_batch(self):
        self.tree.delete(*self.tree.get_children())
        self.batch.clear()

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
               (["--voice-model", self.voice_model()] if self.separate.get() and self.voice_model() else ["--no-separate"])

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
        self.run_jobs([{"cmd": cmd, "out": out, "title": os.path.basename(movie)}])

    def start_batch(self):
        rows = self.tree.get_children()
        if not rows:
            return messagebox.showerror("ProfMute", "Add at least one movie to the list first.")
        dry, out_dir = self.dry.get(), self.path(self.batch_out)
        own_folder, log_beside = self.own_folder.get(), self.log_beside.get()
        if own_folder and not out_dir:
            return messagebox.showerror("ProfMute", "Choose an output folder first.\n\n\"Give each movie its own folder\" "
                                        "makes those folders inside the output folder.")
        shared = self.shared_args(log_box=not log_beside)
        if not shared:
            return
        shared += ["--conflicts", "ask" if self.batch_ask.get() else "auto"]
        jobs, skipped = [], 0
        for iid in rows:
            d = self.batch[iid]
            movie = d["movie"]
            folder = Path(out_dir) if out_dir else movie.parent
            if own_folder:   # Output\Iron Man\Iron Man.clean.mkv (a folder name cannot end in a dot or a space)
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
                             "title": movie.name, "iid": iid})
                self.show_row(iid, "Waiting")
                continue
            skipped += 1
        if not dry:
            outs = [os.path.normcase(j["out"]) for j in jobs]
            if len(set(outs)) < len(outs):
                for j in jobs:
                    self.show_row(j["iid"], "")
                return messagebox.showerror("ProfMute", "Two movies in the list have the same file name, so they would "
                                            "write the same clean copy.\nLeave the output folder empty or remove one.")
            existing = [j["out"] for j in jobs if os.path.exists(j["out"])]
            if existing and not messagebox.askyesno("ProfMute", f"{len(existing)} clean copies already exist and will "
                                                    "be replaced:\n" + "\n".join(existing[:8]) +
                                                    ("\n..." if len(existing) > 8 else "") + "\n\nContinue?"):
                for j in jobs:
                    self.show_row(j["iid"], "")
                return
        if not jobs:
            return self.status.set(f"Nothing to do: all {skipped} movie(s) skipped.")
        self.run_jobs(jobs, skipped)

    # ------------------------------------------------------------ running

    def run_jobs(self, jobs, skipped=0):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        self.jobs, self.job_n, self.job_total = list(jobs), 0, len(jobs)
        self.results = Counter(skipped=skipped)
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
            self.show_row(job["iid"], "Running...")
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
                    self.status.set(batch + part.strip())
                    if part.startswith("4/4") and self.job:
                        self.writing = self.job["out"]
                found = re.match(r"Found (\d+) spots", part)
                if found:
                    self.found = int(found.group(1))
        t.see("end")
        t.configure(state="disabled")

    # ------------------------------------------------------------ conflicts: the user decides

    def ask(self, info):
        """The script waits for an answer about a conflict or an unresolved word: show the question."""
        self.ask_info = info
        unresolved = info.get("kind") == "unresolved"
        what = "unresolved word" if unresolved else "conflict"
        self.status.set(f"Waiting for you: {what} {info['n']} of {info['of']}")
        if winsound:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        win = self.ask_win = tk.Toplevel(self.root)
        win.title(f"ProfMute - {what} {info['n']} of {info['of']}")
        win.transient(self.root)
        win.resizable(False, False)
        if self.dark.get():
            win.configure(background=DARK["bg"])
        box = ttk.Frame(win, padding=18)
        box.pack(fill="both", expand=True)
        movie = self.job["title"] if self.job else ""
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
        button(box, rest[0], rest[1], lambda: self.answer("auto")).grid(
            row=len(facts) + 4, column=0, columnspan=2, sticky="w", pady=(10, 0))
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
        if info.get("kind") == "unresolved":
            said = {"line": "whole line muted", "spot": "estimated spot muted", "leave": "left in",
                    "auto": "left in, and so are the rest"}[reply]
            self.write(f"    Unresolved {info['n']}/{info['of']} at {info['time']} \"{info['word']}\": {said}\n")
        else:
            said = {"mute": "muted", "leave": "left in", "auto": "three listens decide this one and the rest"}[reply]
            self.write(f"    Conflict {info['n']}/{info['of']} at {info['time']} \"{info['word']}\": {said}\n")
        self.status.set("Working...")
        if self.proc:
            try:
                self.proc.stdin.write((reply + "\n").encode())
                self.proc.stdin.flush()
            except OSError:
                pass  # the run ended meanwhile

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
        self.results[outcome] += 1
        if batch:
            self.show_row(job["iid"], row)
            if self.jobs and not self.cancelled:
                return self.next_job()
            for waiting in self.jobs:
                self.show_row(waiting["iid"], "Not run")
            r = self.results
            summary = f"{r['done']} done, {r['failed']} failed, {r['skipped']} skipped" + \
                      (f", {len(self.jobs)} not run" if self.jobs else "")
            self.status.set(("Batch cancelled: " if self.cancelled else "Batch finished: ") + summary + ".")
            self.write(f"\n===== {self.status.get()} =====\n")
        else:
            self.status.set({"cancelled": "Cancelled.", "done": "Done.",
                             "failed": "Something went wrong - see the messages below."}[outcome])
        self.jobs, self.job = [], None
        self.set_running(False)
        threading.Thread(target=self.fetch_models, daemon=True).start()   # a model may have been downloaded just now

    def set_running(self, running):
        for w in self.inputs:
            w.configure(state="disabled" if running else "readonly" if w in (self.model_box, self.voice_box) else "normal")
        if not running and not self.separate.get():
            self.voice_box.configure(state="disabled")
        if not running:
            self.dry_changed()
            self.show_log_box()
        other = 1 - self.tabs.index("current")   # no switching tabs mid-run
        self.tabs.tab(other, state="disabled" if running else "normal")
        self.start_btn.configure(state="disabled" if running else "normal")
        self.cancel_btn.configure(state="normal" if running else "disabled")

    def cancel(self):
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
        self.root.destroy()


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
    App(root).pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    main()
