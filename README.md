# ProfMute

**I could not find a free program that does this locally, on my own PC, so I made one.**

**ProfMute was coded 100% by AI. I did not write any of the code myself.**

ProfMute makes a copy of a movie with the profanity muted. It listens to the audio with
[Whisper](https://github.com/openai/whisper) speech recognition, finds the words on your word list,
and silences just those moments. The picture is not re-encoded, and your original file is never
changed.

It also writes a copy of the subtitles with the same words removed, and a log of every word it
muted so you can check its work.

Everything runs on your own PC. Nothing about your movies is sent anywhere.

## What you need

- Windows 10 or 11, 64-bit.
- About 16 GB of free disk space: 7.5 GB of libraries, 3.1 GB for the default speech model, 0.9 GB
  for the voice removal model, and room for the sound track while it is being cleaned (up to 5 GB
  for a long surround movie, removed afterwards). **Speak a clean word** (off by default) needs
  about 14 GB more for its models, downloaded the first time you use it.
- An internet connection for the first run.
- **A graphics card from NVIDIA is strongly recommended.** With one, a two-hour movie takes
  roughly 10 to 15 minutes. Without one ProfMute still works, on the processor, but the default
  model can take hours per movie; pick a smaller model (see [Models](#models)).
  AMD and Intel graphics cards are not used for speed-up.
- [ffmpeg](https://ffmpeg.org). If it is not installed, ProfMute offers to install it for you.

## Install

Both downloads are on the [latest release](https://github.com/SevynTech/ProfMute/releases/latest).

**With the installer (easiest).** Download the `ProfMute-Setup` exe and run it. It installs for
your Windows account only, so it needs no administrator rights. Its last step downloads Python and
the speech recognition and voice removal libraries (about 4.7 GB), which takes a few minutes.
ProfMute is then in the Start menu. To remove it, use Windows Settings > Apps > Installed apps.

**From the zip (nothing is installed).** Download the `ProfMute` zip, unzip the `ProfMute`
folder somewhere you can write to, such as `Documents` (not `Program Files`), and double-click
`ProfMute.exe`. The first time, it asks to download the same 4.7 GB into that folder. To remove
it, delete the folder.

Windows may show "Windows protected your PC" because neither file is signed. Choose **More info**,
then **Run anyway**. If you would rather not run an exe at all, unzip the zip, open a terminal in
the ProfMute folder and run `tools\uv.exe run python profmute_gui.py`.

**Uninstalling** keeps what you made yours, so installing again picks it up: the word list, the
model lists, your settings and the `log` folder in ProfMute's folder. Everything ProfMute
downloaded into its folder (Python, the libraries, the voice and speaking models) is removed. The
Whisper speech models stay too: they are stored in `%USERPROFILE%\.cache\huggingface`.

To take it all, tick **Remove everything** in the window that appears while uninstalling (it is
unticked unless you tick it): that also removes the word list, model lists, settings and logs, and
the Whisper models ProfMute downloaded. Your clean copies and clean subtitles are never removed.

## Using it

### One movie

1. **Movie file**: choose the movie.
2. **Subtitle file** (optional): leave empty and ProfMute uses a `.srt` next to the movie with the
   same name, or the subtitles inside the movie file.
3. **Output file** and **Clean subtitle file** fill themselves in next to the movie. Change them if
   you like.
4. Press **Start**.

The first run with a model downloads it, which takes a while.

### Batch

On the **Batch** tab, **Add folder...** shows a folder, such as your Movies or TV folder (a network
share works too), as a tree of its folders and movies. Nothing is ticked yet: tick the movies,
shows, seasons or episodes to clean. Ticking a folder ticks everything in it; a folder where only
some of it is ticked shows a partly filled box. **Tick all** and **Untick all** do the whole list,
and Space toggles the selected rows.

For a big library, give the list more room: make the window bigger, drag the divider above the
messages down, or press **Pop out list** to open the list in a window of its own that you can
maximise or move to another screen (close it to put the list back). ProfMute remembers these sizes.

**Add files...** adds single movies, already ticked. Subtitle files next to a movie are picked up
by name; a subtitle file from another folder is matched to the movie with the same name, or assign
one with **Set subtitle...**. Each clean copy goes next to its own movie unless you choose an
output folder.

With an output folder, "Keep the folder layout in the output folder" (on by default) recreates
the folders below the one you added, so a library stays a library:

```
TV\Show\Season 01\Episode.mkv         ->  Output\Show\Season 01\Episode.clean.mkv
Movies\Iron Man (2008)\Iron Man.mkv   ->  Output\Iron Man (2008)\Iron Man.clean.mkv
```

A movie without a folder of its own (added with **Add files...**, or lying loose in the added
folder) gets one named after it, as in `Output\Iron Man\Iron Man.clean.mkv`.

Only ticked movies run, one after another. One failing does not stop the rest, and movies that
already have a clean copy are skipped, so an interrupted batch can simply be started again.

**Start it and walk away.** With "Listen to every movie first, then ask me everything at once"
ticked (the default), a batch runs in three rounds, so you only need to be there for the middle one:

1. **Listening.** Every movie is listened to and checked against its subtitles, without asking
   anything. Start a big batch at night.
2. **Questions.** All the questions about all the movies (the conflicts and unresolved words you
   chose to be asked about) come one after another, each with its movie's name, its number among
   all of them, and the Play buttons. Answer them in the morning.
3. **Writing.** Every clean copy is written with your answers, without asking anything: it runs
   while you are at work.

Each answer is saved as you give it. If you press **Cancel** or close ProfMute during the
questions, start the same batch again later: the movies are not listened to again, and only the
questions you have not answered come back. The saved analyses are kept in a `review` folder next to
ProfMute until each clean copy is written (ones never used are removed after a month).

Unticked, each movie is listened to, asked about and written before the next one starts, so the
batch waits for you at every movie with questions.

If you use Plex, Jellyfin or Emby, point the output folder at a library folder and the clean copies
show up after its next scan.

### Options

- **Put the log next to the clean copy**: on by default, on both tabs. Untick it and every log
  goes to the **Log folder** instead, which starts as a `log` folder next to the program.
- **Word list**: the list of words to mute. **Edit** opens it. See [Word list](#word-list).
- **Whisper model**: bigger is more accurate and slower. See [Models](#models).
- **Padding**: extra silence before and after each word. If you can hear the end of a word, raise
  "after the word".
- **Confirm each word with a second listen**: on by default. See
  [How sure is it?](#how-sure-is-it).
- **Let me hear and decide unresolved words**: on by default. See
  [How sure is it?](#how-sure-is-it).
- **Preview only**: writes only the log, so you can see what would be muted.
- **Fade in and out at each mute**, **Mute only the dialogue channel**, **Check the front
  left/right speakers too**, **Remove only the voice with AI** and **Voice model**: see
  [How a muted word sounds](#how-a-muted-word-sounds).
- **Speak a clean word in the actor's voice (AI)**: off by default. See
  [Speaking a clean word](#speaking-a-clean-word).

## How a muted word sounds

Older versions silenced the whole sound track for each word, so the music and effects dropped out
with it. Now, with every option on (the default), only the voice goes:

- **Fades.** Each mute fades out and back in over 30 ms instead of switching off and on, so there
  is no click. The fades sit in the padding; the word itself is fully muted.
- **Dialogue channel.** In a 5.1 or 7.1 movie, dialogue is almost always in the centre speaker, so
  only that channel is changed; the music and effects in the other speakers keep playing. Stereo
  and mono movies have no separate dialogue channel, so the voice removal below does the work.
- **Front left/right check.** Some mixes put part of the dialogue in the front left and right
  speakers too. ProfMute listens to those two speakers on their own around each muted word, and
  where Whisper hears the word there, it changes those speakers as well. The log says how many
  words that was.
- **Remove only the voice with AI.** Around each muted word, an AI model splits the sound into the
  voice and everything else, and the word is replaced with everything else, so music and effects
  continue underneath. Only the few seconds around each word are processed, not the whole movie,
  which takes about a minute per movie with an NVIDIA graphics card and roughly ten minutes
  without one. Untick it and the changed channels are silenced instead.

The voice models are listed in `voice-models.txt`, next to `ProfMute.exe`, and each is downloaded
the first time it is used:

| Voice model | Download | |
|---|---|---|
| Kim MelBand RoFormer | 0.9 GB | the default: removed the voice most completely in our tests |
| viperx BS RoFormer | 0.6 GB | a second choice; try it if a word can still be heard |

If the voice removal cannot run (no model, no internet on first use), the word is silenced
instead and the log says why.

## Speaking a clean word

> **Experimental.** It works well on calm, normal speech, but it struggles with shouting and
> screaming, and some spots sound off: an odd pause, or a word that doesn't quite sit in the
> line. It is also slow on swear-heavy movies. For the most natural result, leave it off: the
> word is then simply removed and the music and effects keep playing.

With **Speak a clean word in the actor's voice (AI)** ticked, a swear in normal speech is not left
as a gap: the actor says a clean word in its place, in their own voice, inside their own sentence.
"Now get the fuck out of my bar" becomes "Now get the **heck** out of my bar", and "You're a fucking
joke" becomes "You're a **freaking** joke". It works on surround and stereo movies.

How it works, for each sentence with a swear:

1. **Choosing the word.** Gemma, an AI language model, reads the sentence and picks a plain, mild
   word that fits it: "heck" in "where the heck", "screw" in "screw you", "freaking" before a word,
   "jerk" for an insult. It never picks made-up sound-alikes like "fudge". Words you set yourself in
   the word list's `[replacements]` section (see [Word list](#word-list)) always come first.
2. **Saying it.** The voice is separated from the music, and dots.tts, an AI speech model, says the
   sentence again with the clean word, copying the actor's voice and delivery. Only the swear is cut
   out and replaced; the words around it stay the actor's own.
3. **Checking it.** Whisper listens to the new sentence. If the clean word is not clearly there, or
   anything else is off, it is tried again with different settings, up to three times.
4. **Fitting it in.** The new word is placed exactly where the swear was, at the quiet moments around
   it, over the music and effects.

Screams are the weak spot: the speaking AI copies the delivery of the line, and it yells badly.
So each new word is also measured: if it came out yelled (a very high pitch, or a loud word with
no pitch at all), it is tried again with calmer instructions, and if it still yells, that spot is
muted instead. Some swears stay muted as before, and the log's `SPOKEN` part says which and why:
a word that came out yelled (with what was measured), anything that did not pass the check after
three tries, and swears too close to another muted word. The yell check is tuned on male voices;
an excited line from a high voice (a woman or a child) may now and then be muted that way.

The clean subtitles say the spoken word too ("Heck no."), wherever the subtitle line has that swear.

It needs an NVIDIA graphics card. The first time, it downloads about 14 GB of models (see
[Models ProfMute uses](#models-profmute-uses)). It adds about 10 seconds for each sentence with a
swear: 5 to 10 minutes for a typical movie, up to about 40 minutes for one full of swearing.

## How sure is it?

Speech recognition is not perfect, and you should know where it goes wrong:

- It can **miss** a word, especially under music or shouting.
- It can **misplace** a word by up to a second, muting the wrong moment.
- It can, rarely, **hear a word that was not said**.

ProfMute has three defences, and the log shows what each one did.

**Subtitles.** If the movie has English subtitles, they are used as a second opinion. A subtitle
line with a word Whisper missed is listened to again, up to three times: plainly, then with the
subtitle line shown to Whisper as a hint, then on a filtered copy of the sound (100-4000 Hz),
because Whisper misses different words in differently prepared audio. If the word still is not
found, it is listed in the log under `UNRESOLVED` and **not muted**; those are the spots to check
by ear.

Tick "Let me hear and decide unresolved words" and ProfMute asks you about each of those instead.
It knows which subtitle line the word is in, but not exactly when it is said, so it offers three
choices after you have played the line: mute the whole line, mute only its best guess at the spot
(worked out from the words around it that Whisper did hear, and playable first), or leave it.

**Second listens.** With "Confirm each word with a second listen" ticked, every word found is
listened to again on its own. If the two listens disagree about where the word is, a third decides,
and only the place two of them agree on is muted. If no two agree and the subtitles contain the
word, every place it was heard is muted.

**Conflicts.** A conflict is a word Whisper heard that the subtitles do not contain. ProfMute plays
a sound and asks you: it shows the word, the time, what Whisper heard around it and what the
subtitles say, and **Play** lets you hear those few seconds. Choose **Mute it** or **Leave it**. In
a batch, tick "Ask me about conflicts" for the same question (asked all together after every movie
has been listened to, see [Batch](#batch)), or leave it unticked and three listens decide: the word
is muted only if two of them hear it in the same place. Without subtitles there are no conflicts;
everything Whisper hears is muted.

Even so, **watch the result before showing it to anyone**. The log tells you where to look.

## Word list

`words.txt`, next to `ProfMute.exe`, is a plain text file you can edit. Changes apply to the next run.

```
[words]
hell          only the word hell (not hello, not shell)
bitch*        bitch, bitches, bitching ...
*fuck*        any word with fuck in it

[phrases]
son of a bitch*     several words, muted from the first to the last

[censored]    advanced: patterns for bleeped spellings such as f*** and s**t

[cut-off]     word beginnings that subtitles cut off, like "Oh, sh..."

[replacements]
motherfucker* = son of a gun     your own clean word, for "Speak a clean word"
```

Capital letters do not matter, and lines starting with `#` are notes. If a line cannot be
understood, ProfMute says which line and does not start.

`[replacements]` is only used with [Speaking a clean word](#speaking-a-clean-word). Each line is
`swear = clean word`, with `*` working as in `[words]`. A swear listed there always gets your word;
every other swear gets the AI's choice. A clean word that is itself on the list is refused.

You can keep several lists and choose one with the **Word list** box. If `words.txt` is deleted, a
fresh copy with the default words is created the next time ProfMute opens.

## Models ProfMute uses

All of them run on your own PC; nothing is sent anywhere. Each downloads itself the first time it is
needed.

| Model | What it does | Download | Licence | Downloaded |
|---|---|---|---|---|
| Whisper large-v3 (faster-whisper) | listens to the movie and finds the swears | 3.1 GB | MIT | first run |
| Kim MelBand RoFormer | takes the voice out of a muted moment, keeping music and effects | 0.9 GB | MIT | first run with voice removal |
| viperx BS RoFormer | second choice for voice removal | 0.6 GB | none stated | only if you choose it |
| Gemma 4 12B | reads the sentence and chooses the clean word | 7.0 GB | Apache 2.0 | first "Speak a clean word" run |
| dots.tts.edit | says the clean word in the actor's voice, inside their sentence | 5.2 GB | Apache 2.0 | first "Speak a clean word" run |
| wav2vec2 large 960h | finds exactly where each word starts and ends, for a clean cut | 1.2 GB | MIT | first "Speak a clean word" run |
| llama.cpp (an engine, not a model) | runs Gemma on the graphics card | 0.6 GB | MIT | first "Speak a clean word" run |

The Whisper models are in `%USERPROFILE%\.cache\huggingface`, the voice models in the
`voice-models` folder and the "Speak a clean word" models in the `speak-models` folder, both next to
`ProfMute.exe`.

## Models

`models.txt`, next to `ProfMute.exe`, lists the speech recognition (Whisper) models offered in
the window, one per line as `name | note`. The window shows each model's download size and whether
you already have it.

| Model | Download | |
|---|---|---|
| `large-v3` | 3.1 GB | the default: biggest, most accurate, slowest |
| `large-v3-turbo` | 1.6 GB | much faster, a little less accurate |
| `small.en` | 0.5 GB | fast, misses more words |
| `tiny.en` | 80 MB | fastest, least accurate |

ProfMute works in English only.

### Adding a Whisper model

1. Close ProfMute and open `models.txt` in a text editor such as Notepad.
2. Add a line `name | note`. The name can be:
   - a model name faster-whisper knows, such as `medium` or `distil-large-v3.5`;
   - a Hugging Face repository holding a model converted for faster-whisper (CTranslate2
     format), written as `someone/some-model`;
   - a folder on your PC holding such a model, such as `D:\Models\my-whisper`.
3. Save the file and open ProfMute. The model is in the **Whisper model** list, and it downloads
   itself the first time you use it.

The first line of the file is the default. To remove a model from the list, delete its line;
deleting `models.txt` brings back the original list.

### Adding a voice model

The voice models (see [How a muted word sounds](#how-a-muted-word-sounds)) are listed in
`voice-models.txt` the same way, one per line:

```
name | architecture | weights address | settings address
```

- **architecture** is `mel_band_roformer` or `bs_roformer`, the two kinds ProfMute can run.
- **weights address** is a download link to the model's `.ckpt` file.
- **settings address** is a download link to its settings file (`.yaml`), in the format of
  [Music-Source-Separation-Training](https://github.com/ZFTurbo/Music-Source-Separation-Training),
  where many such files can be found. Use links to the raw file, not to a web page.
- The model has to be a *vocals* model with one output: its settings file says `num_stems: 1`
  and `target_instrument: vocals`.

Save the file, open ProfMute, and choose the model in the **Voice model** list. It downloads into
the `voice-models` folder the first time it is used. The first line of the file is the default.

## What you get

- `<movie>.clean.mkv`: the copy with the words muted. Video and other tracks are copied as they
  are; only the cleaned audio track is re-encoded (AAC).
- `<movie>.clean.en.srt`: the subtitles with the words deleted (or, with **Speak a clean word**, the
  spoken word in their place). The lines and their timing are the original file's, shifted only when
  the whole file runs early or late. Media players and Plex pick it up by its name. **The subtitle tracks inside the clean `.mkv` are copies of the originals and still
  contain the words**, so select the `.srt` when watching.
- `<movie>.profmute.txt`, next to the clean copy unless you chose the log folder: every muted
  spot with its time and length, how conflicts were settled, anything `UNRESOLVED`, and the
  settings used.

Every option in the window explains itself when the mouse rests on it.

## Command line

Everything the window does is available from a terminal in the ProfMute folder:

```
tools\uv.exe run python profmute.py "D:\Movies\Some Movie.mkv" --confirm
tools\uv.exe run python profmute.py --help
```

To listen now and answer later, as a batch does: run once with `--review-file answers.json`
(it listens, saves the questions and writes nothing), add your answers to that file, then run the
same command with `--from-review answers.json` instead to write the clean copy.

## Building from source

You need [uv](https://docs.astral.sh/uv/) and Windows. To run from a clone of this repository:

```
uv sync
uv run python profmute_gui.py
```

The release files are assembled by `build_dist.py`. The installer also needs
[Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install --id JRSoftware.InnoSetup -e`);
without it only the zip is built.

```
uv run python build_dist.py
```

It compiles the small launcher (`launcher\ProfMute.cs`), copies an explicit list of files into
`dist\ProfMute`, zips that folder, and builds the installer from it (`installer\ProfMute.iss`).

## License

ProfMute is released under the MIT license; see `LICENSE`. It builds on faster-whisper,
CTranslate2, OpenAI's Whisper models, PyTorch, the voice separation code and models from
Music-Source-Separation-Training and their authors, ffmpeg and uv; see `THIRD-PARTY-NOTICES.md`.

Use it on media you have the right to copy and modify.
