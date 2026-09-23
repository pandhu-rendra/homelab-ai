#!/usr/bin/env python3
from textual.widgets import RichLog
from rich.text import Text

# Create a RichLog and write some content
rl = RichLog()
rl.write("Hello World")
rl.write(Text("This is a test"))

# Check text property
print("Has text property:", hasattr(rl, 'text'))
print("Text content:", rl.text[:50] if hasattr(rl, 'text') else "N/A")

# Check get_selection
print("Has get_selection:", hasattr(rl, 'get_selection'))
try:
    selection = rl.get_selection() if hasattr(rl, 'get_selection') else None
    print("Selection result type:", type(selection))
    print("Selection:", selection)
except Exception as e:
    print("Error calling get_selection:", e)
