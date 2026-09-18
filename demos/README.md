# Demo recordings

The three GIFs in the README, plus the inputs and the recipes that produce them.

| file | what it shows |
|---|---|
| `compact.gif` | `lcc compact` dropping noise from a 22-block dossier, then `lcc explain` showing why each block went |
| `compile.gif` | `lcc optimize` turning a brief dumped from three places into a structured XML prompt |
| `audio-to-prompt.gif` | `lcc intake` cleaning a Whisper-style transcript and compiling it into a prompt |

## Regenerating them

```bash
python3 demos/make_gifs.py            # all three
python3 demos/make_gifs.py compact    # one
```

Requires Pillow (the system `python3` has it) and `lcc` on PATH. The script runs the real
commands, captures their real output, and draws it into frames, so the GIFs are a recording of
what the tool actually printed rather than a mock-up. The render is deterministic: regenerating
produces byte-identical files.

### Why rendered rather than recorded

`vhs` 0.12.0 is installed and does **not** work on this machine. It exits `0`, prints
`Creating demos/compact.gif...`, and writes no file. That was reproduced with a one-command tape
(`echo`, `Sleep 2s`) as well as with the real ones, so it is not a tape problem:

- `ttyd 1.7.7` works on its own (serves `HTTP 200`).
- `ffmpeg 9.0.1` works on its own.
- The failure is therefore inside vhs's recording path.

The cause is **not** identified. `ttyd` 1.6.3 is the usual suspect for vhs 0.12, but that release
publishes Linux binaries only, so it could not be tested here without building it. If you can run
`vhs demos/compact.tape` and get a GIF, the tapes are correct and you should use them: they are
the same recipes in the standard format.

The `*.tape` files are checked by `demos/validate_tapes.py`, because `vhs validate` parses a tape
but does not check the command the tape types — a tape can validate and still type something that
fails. A syntax check is not enough either (`lcc compact --provider` is valid bash, and so is a
command whose flags were swallowed by an unbalanced quote), so the script can run them:

```bash
python3 demos/validate_tapes.py          # syntax check, fast
python3 demos/validate_tapes.py --run    # run every command the tapes type
```

`--run` is the check that counts, and it currently passes against the real `lcc`.

## Inputs

| file | purpose |
|---|---|
| `compact-dossier.md` | a dossier with a stable prefix, tool output, logs, chatter, and one item of each ground-truth category |
| `messy-brief.md` | a brief with repeated paragraphs, page markers, an email signature and a decorative rule |
| `audio-transcript.txt` | a Whisper-style capture with English and Portuguese fillers, `[Music]`, and a subtitle credit |
| `cleaning_steps.py` | prints the cleaning steps from an `lcc optimize` report, so no tape needs nested shell quoting |
| `validate_tapes.py` | checks that the tapes type complete, working commands |
