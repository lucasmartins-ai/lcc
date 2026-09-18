# GIF: a scattered brief compiled into a structured prompt.
#
#   vhs demos/compile.tape
#
# Deterministic: normalize, remove boilerplate, drop near-duplicates, build the prompt.
# Same input, same output, every time, with no model in the loop.

Output "demos/compile.gif"

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

Type "# A brief dumped from three places: repeated paragraphs, page markers, a signature"
Enter
Sleep 800ms

Type "lcc optimize demos/messy-brief.md -q 'What should we change about the checkout?' --template claude_xml -o /tmp/compiled.md -r /tmp/compiled.json"
Enter
Sleep 2s

Type "# Nothing is summarised or rewritten. Redundant text is removed, and the report says what"
Enter
Sleep 400ms

Type "python3 demos/cleaning_steps.py /tmp/compiled.json"
Enter
Sleep 3s

Type "# And the compiled prompt itself"
Enter
Sleep 400ms

Type "head -18 /tmp/compiled.md"
Enter
Sleep 4s
