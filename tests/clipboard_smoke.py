"""Exercise real Windows clipboard restoration using our own Tk copy event.
Foreground acquisition is deliberately not forced by this automated test.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import threading
import tkinter as tk
from unittest.mock import patch
import clipboard_capture as capture

root = tk.Tk()
root.title('TTS - Zwischenablage-Prüfung')
field = tk.Text(root, exportselection=False)
field.pack()
sample = 'Ein ausgewählter Testtext.'
field.insert('1.0', sample)
field.tag_add('sel', '1.0', 'end-1c')
original = capture._text()
result = {}
copy_requested = threading.Event()

def key_event(vk, scan, flags, extra):
    if vk == 67 and flags == 0:
        copy_requested.set()

def run():
    def worker():
        result['text'] = capture.capture_selection(threading.Event())
        result['restored'] = capture._text() == original
        result['done'] = True
    threading.Thread(target=worker, daemon=True).start()

def poll():
    if copy_requested.is_set():
        copy_requested.clear()
        field.event_generate('<<Copy>>')
    if result.get('done'):
        root.destroy()
    else:
        root.after(15, poll)

root.after(400, run)
root.after(100, poll)
root.after(5000, root.destroy)
with patch.object(capture.u32, 'keybd_event', side_effect=key_event):
    root.mainloop()
assert result.get('text') == sample, 'Selection copy failed'
assert result.get('restored'), 'Clipboard restoration failed'
print('Real Windows clipboard / controlled copy / original restoration: OK')
