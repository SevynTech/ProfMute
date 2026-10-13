# Changelog

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
