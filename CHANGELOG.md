# Changelog

## 1.3.0 - 2026-10-15

### Added

- **Speak a clean word in the actor's voice (experimental).** A new option, off by default: instead of a gap, a
  swear in normal speech is replaced by a clean word said in the actor's own voice, inside their own
  sentence ("get the heck out of my bar"). An AI model (Gemma 4 12B) picks a plain word that fits
  the sentence, another (dots.tts) says it, Whisper checks it (up to three tries), and the new word
  is cut in exactly where the swear was, over the music and effects. A word that comes out yelled
  is tried again calmer, and muted if it still yells. The clean subtitles say the spoken word
  ("Heck no."). Anything that fails the check stays muted; the log's new `SPOKEN` part says what
  happened to each sentence. Needs an NVIDIA graphics card; the models (about 14 GB) download on
  first use. On the command line: `--speak`.
- **`[replacements]` in the word list:** `swear = clean word` lines choose the spoken word yourself;
  they always win over the AI's choice.
- The README lists every AI model ProfMute uses, what it does, its size and licence.
- **Batch: pick from a whole library.** **Add folder...** now shows the folder as a tree of its
  folders and movies, with a box on each row. Tick single movies or episodes, or tick a folder to
  take a whole show or season; a partly ticked folder shows a partly filled box. New buttons
  **Tick all** and **Untick all**, and Space ticks the selected rows. Only ticked movies are
  cleaned. Works on network shares, so you can point it at the media folders of a Plex, Jellyfin
  or Emby server.
- **More room for the list.** A taller window now makes the batch list taller. The divider above
  the messages can be dragged. **Pop out list** opens the list in a window of its own, to maximise
  or move to another screen; closing it puts the list back. The window size, the divider and
  the list's own window are remembered.

### Changed

- "Give each movie its own folder in the output folder" is now "Keep the folder layout in the
  output folder". The clean copies keep the folders they were in below the added folder, as in
  `Output\Show\Season 01\Episode.clean.mkv`. A movie without a folder of its own still gets one
  named after it.
- Movies added with **Add files...** start ticked; folders start with nothing ticked.
- New defaults: "Confirm each word with a second listen", "Let me hear and decide unresolved
  words" and "Keep the folder layout in the output folder" are now on. A choice you made yourself
  before is kept.
- The word list has "blowjob" and "blow job" in it. An existing `words.txt` is not changed; add
  `blowjob*` under `[words]` and `blow job*` under `[phrases]` to have them.
- The README explains how to add Whisper models and voice models.
- The first-time library download is about 4.7 GB (was 4.5 GB), for the speaking libraries.

### Fixed

- Subtitles made for a release that starts differently are lined up again when they are up to two
  minutes out (was 30 seconds); before, they were ignored. Saving Private Ryan's common subtitle
  file, for example, runs 40 seconds late.
- Subtitle lines that the line-up moves to before the start of the movie are dropped, instead of
  showing up in the log with a nonsense time.

## 1.2.0 - 2026-10-14

### Added

- **The music keeps playing under a muted word.** Before, a mute silenced the whole sound track.
  Now, by default, only the voice is taken out:
  - **Dialogue channel.** In 5.1 and 7.1 movies only the centre (dialogue) channel is changed;
    the other speakers keep playing. Checkbox "Mute only the dialogue channel in surround movies";
    on the command line `--all-channels` turns it off.
  - **Front left/right check.** Whisper also listens to the front left and right speakers around
    each muted word, and where it hears the word there too, those speakers are changed as well.
    Checkbox "Check the front left/right speakers too"; `--no-front-check` turns it off.
  - **AI voice removal.** Around each muted word, an AI model separates the voice from the music
    and effects, and the word is replaced with the music and effects alone. Works for stereo
    movies too. Checkbox "Remove only the voice with AI (keeps music)"; `--no-separate` turns it
    off. Two models are offered in the new **Voice model** box: Kim MelBand RoFormer (the
    default) and viperx BS RoFormer. Each downloads the first time it is used. The list is in
    the new `voice-models.txt`; `--voice-model` and `--list-voice-models` on the command line.
- **Fades.** Each mute fades out and in over 30 ms instead of switching off and on, so there are
  no clicks. Checkbox "Fade in and out at each mute"; `--no-fade` turns it off.
- The log says how each movie's sound was changed.

### Changed

- The cleaned audio is now written by ProfMute itself rather than by an ffmpeg volume filter. Every
  other stream is copied unchanged, in its original order, with its language, title and default
  flag. While a movie is written, its sound track is kept in a temporary file next to the output,
  up to about 5 GB for a long surround movie.
- The first-time download is larger, about 4.5 GB instead of 2.2 GB, because the voice removal
  needs PyTorch.

## 1.1.0 - 2026-10-12

### Added

- **You can decide unresolved words.** An unresolved word is one the subtitles have but Whisper
  never heard, so ProfMute knows which subtitle line it is in but not exactly when it is said.
  With the new checkbox "Let me hear and decide unresolved words", ProfMute plays a sound and shows
  each one. You can play the line, then mute the whole line, mute only an estimated spot, or leave
  it. The estimated spot is worked out from the words around it that Whisper did hear, and it can
  be played before you choose. On the command line: `--unresolved ask`.
- **Batch: a folder for each movie.** "Give each movie its own folder in the output folder" puts
  every clean copy and its clean subtitles in a folder named after the movie, as in
  `Output\Iron Man\Iron Man.clean.mkv`.
- **Log next to the clean copy.** A new checkbox on both tabs, "Put the log next to the clean
  copy". Untick it to send all logs to the Log folder instead.
- **Mouse-over explanations** for every setting in the window and every button in the pop-ups.

### Changed

- In the window, the log is now saved next to the clean copy by default. Before, it went to the
  `log` folder next to the program; that is still where it goes when the checkbox is unticked, and
  still the default on the command line.
- The `UNRESOLVED` part of the log now says what was decided for each line.
- The batch checkbox "Pause and ask me about conflicts (otherwise three listens decide)" is now
  labelled "Pause and ask me about conflicts"; the rest is in its mouse-over explanation.

## 1.0.0 - 2026-10-11

First release.

- Mutes the words on an editable word list in a copy of the movie; the original is never changed.
- Writes clean subtitles and a log of every muted spot.
- Uses the movie's subtitles to double-check Whisper, re-listening to lines whose words were
  missed, with a filtered copy of the sound as a last try.
- Optional second listens to confirm where each word is.
- Conflicts (a word Whisper heard that the subtitles do not have) are put to you, or decided by
  three listens.
- One movie or a batch; a choice of Whisper models; runs on an NVIDIA graphics card or, slowly,
  on the processor.
- Installer and zip for Windows.
