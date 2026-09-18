# GIF: relevance compaction, then the decision trail behind it.
#
#   vhs demos/compact.tape
#
# Uses the local provider on purpose: no API key, no network, so the recording is
# reproducible by anyone who clones the repository.

Output "demos/compact.gif"

Set Shell bash
Set FontSize 14
Set FontFamily "MesloLGS NF,JetBrains Mono,Menlo,monospace"
Set Width 1080
Set Height 640
Set Padding 16
Set Margin 0
Set Theme "Dracula"
Set TypingSpeed 26ms
Set CursorBlink false
Set WindowBar Colorful
Set BorderRadius 8

# --- the transform --------------------------------------------------------------
Type "# 23 blocks from a real dossier: a stable prefix, tool output, logs, chatter"
Enter
Sleep 700ms

Type "lcc compact demos/compact-dossier.md -q 'What is wrong with the booking operation?' --provider mechanical -o /tmp/compacted.md -r /tmp/report.json"
Enter
Sleep 2s

# --- and why --------------------------------------------------------------------
Type "# Every keep, trim and drop is recorded, with the reason"
Enter
Sleep 500ms

Type "lcc explain /tmp/report.json --source demos/compact-dossier.md --only drop --limit 3"
Enter
Sleep 4s
