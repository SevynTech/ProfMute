# ProfMute

ProfMute makes a copy of a movie with the profanity muted. It listens to the audio with
[Whisper](https://github.com/openai/whisper) speech recognition, finds the words on your word list,
and silences just those moments. The picture is not re-encoded, and your original file is never
changed.

It also writes a copy of the subtitles with the same words removed, and a log of every word it
muted so you can check its work.

Everything runs on your own PC. Nothing about your movies is sent anywhere.

## What you need

- Windows 10 or 11, 64-bit.
- About 6 GB of free disk space (2.2 GB of libraries plus 3.1 GB for the default speech model).
- An internet connection for the first run.
- **A graphics card from NVIDIA is strongly recommended.** With one, a two-hour movie takes
  roughly 10 to 15 minutes. Without one ProfMute still works, on the processor, but the default
  model can take hours per movie; pick a smaller model (see [Models](#models)).
  AMD and Intel graphics cards are not used for speed-up.
- [ffmpeg](https://ffmpeg.org). If it is not installed, ProfMute offers to install it for you.

## Install

1. Download `ProfMute-1.0.0.zip` from the
   [latest release](https://github.com/SevynTech/ProfMute/releases/latest) and unzip the
   `ProfMute` folder somewhere you can write to, such as `Documents`. Do not put it in
   `Program Files`.
2. Double-click `ProfMute.exe`.
3. The first time, it asks to download Python and the speech recognition libraries (about 2.2 GB)
   into the ProfMute folder. Say yes and wait for the black window to close. This happens once.

Windows may show "Windows protected your PC" because the launcher is not signed. Choose
**More info**, then **Run anyway**. If you would rather not run the exe at all, open a terminal in
the ProfMute folder and run `tools\uv.exe run python profmute_gui.py` instead.

To remove ProfMute, delete its folder. The speech models are stored separately, in
`%USERPROFILE%\.cache\huggingface`.

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

On the **Batch** tab, add movies with **Add files...** or a whole folder tree with
**Add folder...**. Subtitle files next to a movie are picked up by name; a subtitle file from
another folder is matched to the movie with the same name, or assign one with **Set subtitle...**.
Each clean copy goes next to its own movie unless you choose an output folder.

Movies run one after another. One failing does not stop the rest, and movies that already have a
clean copy are skipped, so an interrupted batch can simply be started again.

### Options

- **Log folder**: where the logs go. Defaults to a `log` folder next to the program.
- **Word list**: the list of words to mute. **Edit** opens it. See [Word list](#word-list).
- **Whisper model**: bigger is more accurate and slower. See [Models](#models).
- **Padding**: extra silence before and after each word. If you can hear the end of a word, raise
  "after the word".
- **Confirm each word with a second listen**: see below.
- **Preview only**: writes only the log, so you can see what would be muted.

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

**Second listens.** With "Confirm each word with a second listen" ticked, every word found is
listened to again on its own. If the two listens disagree about where the word is, a third decides,
and only the place two of them agree on is muted. If no two agree and the subtitles contain the
word, every place it was heard is muted.

**Conflicts.** A conflict is a word Whisper heard that the subtitles do not contain. ProfMute plays
a sound and asks you: it shows the word, the time, what Whisper heard around it and what the
subtitles say, and **Play** lets you hear those few seconds. Choose **Mute it** or **Leave it**. In
a batch, tick "Pause and ask me about conflicts" for the same question, or leave it unticked and
three listens decide: the word is muted only if two of them hear it in the same place. Without
subtitles there are no conflicts; everything Whisper hears is muted.

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
```

Capital letters do not matter, and lines starting with `#` are notes. If a line cannot be
understood, ProfMute says which line and does not start.

You can keep several lists and choose one with the **Word list** box. If `words.txt` is deleted, a
fresh copy with the default words is created the next time ProfMute opens.

## Models

`models.txt`, next to `ProfMute.exe`, lists the models offered in the window, one per line as
`name | note`. The window shows each model's download size and whether you already have it.

| Model | Download | |
|---|---|---|
| `large-v3` | 3.1 GB | the default: biggest, most accurate, slowest |
| `large-v3-turbo` | 1.6 GB | much faster, a little less accurate |
| `small.en` | 0.5 GB | fast, misses more words |
| `tiny.en` | 80 MB | fastest, least accurate |

A name can also be a Hugging Face repository (`someone/some-model`) holding a model converted for
faster-whisper, or a folder on your PC containing one. ProfMute works in English only.

## What you get

- `<movie>.clean.mkv`: the copy with the words muted. Video and other tracks are copied as they
  are; only the cleaned audio track is re-encoded (AAC).
- `<movie>.clean.en.srt`: the subtitles with the words deleted. Media players and Plex pick it up
  by its name. **The subtitle tracks inside the clean `.mkv` are copies of the originals and still
  contain the words**, so select the `.srt` when watching.
- `<movie>.profmute.txt` in the log folder: every muted spot with its time and length, how
  conflicts were settled, anything `UNRESOLVED`, and the settings used.

## Command line

Everything the window does is available from a terminal in the ProfMute folder:

```
tools\uv.exe run python profmute.py "D:\Movies\Some Movie.mkv" --confirm
tools\uv.exe run python profmute.py --help
```

## Building from source

You need [uv](https://docs.astral.sh/uv/) and Windows. To run from a clone of this repository:

```
uv sync
uv run python profmute_gui.py
```

The release zip is assembled by `build_dist.py`:

```
uv run python build_dist.py
```

It compiles the small launcher (`launcher\ProfMute.cs`), copies an explicit list of files into
`dist\ProfMute`, and makes the zip.

## License

ProfMute is released under the MIT license; see `LICENSE`. It builds on faster-whisper,
CTranslate2, OpenAI's Whisper models, ffmpeg and uv; see `THIRD-PARTY-NOTICES.md`.

Use it on media you have the right to copy and modify.
