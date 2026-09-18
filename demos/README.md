# Demo recordings

The three GIFs in the README, plus the inputs and the recipes that produce them.

| file | what it shows |
|---|---|
| `compact.gif` | `lcc compact` dropping noise from a 23-block dossier, then `lcc explain` showing why each block went |
| `compile.gif` | `lcc optimize` turning a brief dumped from three places into a structured XML prompt |
| `audio-to-prompt.gif` | `lcc intake` cleaning a Whisper-style transcript and compiling it into a prompt |

## Regenerating them

```bash
python3 demos/make_gifs.py            # all three
python3 demos/make_gifs.py compact    # one
```

Requires Pillow (the system `python3` has it) and `lcc` on PATH. The script runs the real
commands, captures their real output, and draws it into frames, so the GIFs are a recording of
what the tool actually printed rather than a mock-up.

It works this way because a terminal recorder is not available here: `vhs` 0.12 reports success
and writes no file against the `ttyd` 1.7 that Homebrew installs. The `*.tape` files are kept
because they are the same recipes in the standard format, and they will work once that
combination is fixed upstream.

## Inputs

| file | purpose |
|---|---|
| `compact-dossier.md` | a dossier with a stable prefix, tool output, logs, chatter, and one item of each ground-truth category |
| `messy-brief.md` | a brief with repeated paragraphs, page markers, an email signature and a decorative rule |
| `audio-transcript.txt` | a Whisper-style capture with English and Portuguese fillers, `[Music]`, and a subtitle credit |
| `cleaning_steps.py` | prints the cleaning steps from an `lcc optimize` report, so the tapes never need nested shell quoting |
