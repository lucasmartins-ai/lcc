# GIF: a messy voice transcript turned into a structured prompt.
#
#   vhs demos/audio-to-prompt.tape
#
# Shows the speech cleaner doing its job on a Whisper-style capture: fillers dropped
# in English and Portuguese, audio tags stripped, speaker turns collapsed.

Output "demos/audio-to-prompt.gif"

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

Type "# What a Whisper capture actually looks like: fillers, [Music], a subtitle credit"
Enter
Sleep 800ms

Type "head -9 demos/audio-transcript.txt"
Enter
Sleep 3s

Type "# lcc detects the transcript, cleans it, and compiles a prompt from it"
Enter
Sleep 400ms

Type "lcc intake demos/audio-transcript.txt -q 'What is the checkout plan?' --template claude_xml -o /tmp/from-audio.md"
Enter
Sleep 3s

Type "# The cleaned context that came out of the audio"
Enter
Sleep 400ms

Type "sed -n '/<context>/,/<\\/context>/p' /tmp/from-audio.md | head -12"
Enter
Sleep 4s
