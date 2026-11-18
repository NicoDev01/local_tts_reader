"""Exercise real Windows clipboard restoration using our own Tk copy event.
Foreground acquisition is deliberately not forced by this automated test.

Runs three times, with text, a screenshot-like bitmap and an Office-like metafile already in the
clipboard. Windows derives extra formats from the last two (CF_PALETTE, CF_METAFILEPICT), which
once made every capture fail with "Kein Text markiert".
"""
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import threading
import tkinter as tk
from unittest.mock import patch
import clipboard_capture as capture

u32, k32, gdi = capture.u32, capture.k32, capture.gdi
gdi.CreateEnhMetaFileW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.LPCWSTR]
gdi.CreateEnhMetaFileW.restype = wintypes.HDC
gdi.CloseEnhMetaFile.argtypes = [wintypes.HDC]
gdi.CloseEnhMetaFile.restype = wintypes.HANDLE
gdi.Rectangle.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]


def put(fmt, handle):
    capture._open()
    try:
        u32.EmptyClipboard()
        if not u32.SetClipboardData(fmt, handle):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        u32.CloseClipboard()


def put_text(text):
    data = ctypes.create_unicode_buffer(text)
    handle = k32.GlobalAlloc(2, ctypes.sizeof(data))
    ctypes.memmove(k32.GlobalLock(handle), data, ctypes.sizeof(data))
    k32.GlobalUnlock(handle)
    put(13, handle)


def put_bitmap():
    # 2 x 2 pixels, 32 bit, as CF_DIB: what screenshot tools and browsers put on the clipboard.
    header = (ctypes.c_uint32 * 10)(40, 2, 2, 1 | 32 << 16, 0, 16, 0, 0, 0, 0)
    pixels = bytes([0, 0, 255, 0, 0, 255, 0, 0, 255, 0, 0, 0, 255, 255, 255, 0])
    data = bytes(header) + pixels
    handle = k32.GlobalAlloc(2, len(data))
    ctypes.memmove(k32.GlobalLock(handle), data, len(data))
    k32.GlobalUnlock(handle)
    put(8, handle)
    return data


def put_metafile():
    dc = gdi.CreateEnhMetaFileW(None, None, None, None)
    gdi.Rectangle(dc, 0, 0, 20, 10)
    put(14, gdi.CloseEnhMetaFile(dc))


def formats():
    capture._open()
    try:
        found, fmt = [], 0
        while fmt := u32.EnumClipboardFormats(fmt):
            found.append(fmt)
        return found
    finally:
        u32.CloseClipboard()


def dib():
    capture._open()
    try:
        handle = u32.GetClipboardData(8)
        size = k32.GlobalSize(handle)
        data = ctypes.string_at(k32.GlobalLock(handle), size)
        k32.GlobalUnlock(handle)
        return data
    finally:
        u32.CloseClipboard()


def check(prepare, restored, label):
    prepare()
    print(f'{label}: Formate vorher {formats()}')
    root = tk.Tk()
    root.title('TTS - Zwischenablage-Prüfung')
    field = tk.Text(root, exportselection=False)
    field.pack()
    sample = 'Ein ausgewählter Testtext.'
    field.insert('1.0', sample)
    field.tag_add('sel', '1.0', 'end-1c')
    result = {}
    copy_requested = threading.Event()

    def key_event(vk, scan, flags, extra):
        if vk == 67 and flags == 0:
            copy_requested.set()

    def run():
        def worker():
            result['text'] = capture.capture_selection(threading.Event())
            result['restored'] = restored()
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
    assert result.get('text') == sample, f'{label}: selection copy failed ({result.get("text")!r})'
    assert result.get('restored'), f'{label}: clipboard restoration failed'
    print(f'{label}: copy and restoration OK')


original = 'Alter Inhalt der Zwischenablage.'
check(lambda: put_text(original), lambda: capture._text() == original, 'Text')
bitmap = {}
check(lambda: bitmap.update(data=put_bitmap()), lambda: dib() == bitmap['data'], 'Bild (CF_DIB + CF_PALETTE)')
check(put_metafile, lambda: 14 in formats(), 'Office-Grafik (CF_ENHMETAFILE + CF_METAFILEPICT)')
print('Real Windows clipboard / controlled copy / original restoration: OK')
