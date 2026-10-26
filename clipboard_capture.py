"""Fresh selection capture with an atomic, format-preserving clipboard restore."""
import ctypes
from ctypes import wintypes
import logging
import threading
import time

u32 = ctypes.WinDLL('user32', use_last_error=True)
k32 = ctypes.WinDLL('kernel32', use_last_error=True)
gdi = ctypes.WinDLL('gdi32', use_last_error=True)
u32.GetClipboardSequenceNumber.restype = wintypes.DWORD
u32.GetForegroundWindow.restype = wintypes.HWND
u32.GetClipboardData.argtypes = [wintypes.UINT]
u32.GetClipboardData.restype = wintypes.HANDLE
u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
u32.SetClipboardData.restype = wintypes.HANDLE
u32.OpenClipboard.argtypes = [wintypes.HWND]
u32.CopyImage.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
u32.CopyImage.restype = wintypes.HANDLE
u32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
    wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
u32.CreateWindowExW.restype = wintypes.HWND
u32.DestroyWindow.argtypes = [wintypes.HWND]
for name in ('GlobalLock', 'GlobalSize', 'GlobalUnlock', 'GlobalFree'):
    getattr(k32, name).argtypes = [wintypes.HGLOBAL]
k32.GlobalLock.restype = ctypes.c_void_p
k32.GlobalSize.restype = ctypes.c_size_t
k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
k32.GlobalAlloc.restype = wintypes.HGLOBAL
gdi.CopyEnhMetaFileW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR]
gdi.CopyEnhMetaFileW.restype = wintypes.HANDLE
gdi.DeleteEnhMetaFile.argtypes = [wintypes.HANDLE]
gdi.DeleteObject.argtypes = [wintypes.HANDLE]
_capture_lock = threading.Lock()


def _open(hwnd=None):
    for _ in range(20):
        if u32.OpenClipboard(hwnd):
            return
        time.sleep(.01)
    raise OSError('Zwischenablage wird von einem anderen Programm verwendet')


def _read_text():
    try:
        _open()
    except OSError:
        return None, None
    try:
        handle = u32.GetClipboardData(13)
        if not handle:
            return '', u32.GetClipboardSequenceNumber()
        ptr = k32.GlobalLock(handle)
        if not ptr:
            return None, None
        try:
            value = ctypes.wstring_at(ptr)
            return value, u32.GetClipboardSequenceNumber()
        finally:
            k32.GlobalUnlock(handle)
    finally:
        u32.CloseClipboard()


def _text():
    return _read_text()[0]


class Snapshot:
    """Own independent copies, never an OLE wrapper pointing at a changing clipboard."""
    def __init__(self, hwnd):
        self.items = []
        self.hwnd = hwnd
        _open(hwnd)
        try:
            fmt = 0
            total = 0
            while True:
                fmt = u32.EnumClipboardFormats(fmt)
                if not fmt:
                    break
                source = u32.GetClipboardData(fmt)
                if not source:
                    raise OSError('Ein Zwischenablageformat konnte nicht gesichert werden')
                if fmt in (2, 0x82):  # bitmap
                    handle = u32.CopyImage(source, 0, 0, 0, 0x2000)
                    free = gdi.DeleteObject
                elif fmt in (14, 0x8e):  # enhanced metafile
                    handle = gdi.CopyEnhMetaFileW(source, None)
                    free = gdi.DeleteEnhMetaFile
                elif fmt in (3, 9, 0x80, 0x83):
                    # Fail before copying; never destroy a format we cannot preserve.
                    raise OSError('Dieses Zwischenablageformat kann nicht sicher wiederhergestellt werden')
                else:
                    size = k32.GlobalSize(source)
                    total += size
                    if not size or total > 64 * 1024 * 1024:
                        raise OSError('Zwischenablageformat zu groß oder nicht kopierbar')
                    handle = k32.GlobalAlloc(2, size)
                    if not handle:
                        raise MemoryError('Zwischenablage konnte nicht gesichert werden')
                    src, dst = k32.GlobalLock(source), k32.GlobalLock(handle)
                    if not src or not dst:
                        if src: k32.GlobalUnlock(source)
                        if dst: k32.GlobalUnlock(handle)
                        k32.GlobalFree(handle)
                        raise OSError('Zwischenablage konnte nicht gesperrt werden')
                    try:
                        ctypes.memmove(dst, src, size)
                    finally:
                        k32.GlobalUnlock(source)
                        k32.GlobalUnlock(handle)
                    free = k32.GlobalFree
                if not handle:
                    raise ctypes.WinError(ctypes.get_last_error())
                self.items.append([fmt, handle, free])
        except Exception:
            self.close()
            raise
        finally:
            u32.CloseClipboard()

    def restore(self, sequence):
        _open(self.hwnd)
        try:
            # Check while holding the clipboard lock: a later copy always wins.
            if u32.GetClipboardSequenceNumber() != sequence:
                return
            if not u32.EmptyClipboard():
                raise ctypes.WinError(ctypes.get_last_error())
            for item in self.items:
                fmt, handle, _ = item
                if not u32.SetClipboardData(fmt, handle):
                    raise ctypes.WinError(ctypes.get_last_error())
                item[1] = None  # Windows owns this memory now.
        finally:
            u32.CloseClipboard()

    def close(self):
        for _, handle, free in self.items:
            if handle:
                free(handle)
        self.items.clear()


def capture_selection(cancel, restore=True):
    if not _capture_lock.acquire(blocking=False):
        return ''
    snapshot, hwnd = None, None
    try:
        foreground = u32.GetForegroundWindow()
        deadline = time.monotonic() + 2
        while any(u32.GetAsyncKeyState(vk) & 0x8000 for vk in (16, 17, 18, 91, 92)):
            if cancel.wait(.02) or time.monotonic() >= deadline:
                return ''
        if cancel.is_set() or u32.GetForegroundWindow() != foreground:
            return ''
        if restore:
            hwnd = u32.CreateWindowExW(0, 'STATIC', '', 0, 0, 0, 0, 0, wintypes.HWND(-3), None, None, None)
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            snapshot = Snapshot(hwnd)
        before = u32.GetClipboardSequenceNumber()
        u32.keybd_event(17, 0, 0, 0)
        try:
            u32.keybd_event(67, 0, 0, 0)
            u32.keybd_event(67, 0, 2, 0)
        finally:
            u32.keybd_event(17, 0, 2, 0)
        deadline = time.monotonic() + .8
        copied_sequence, result = None, ''
        while time.monotonic() < deadline:
            time.sleep(.015)
            sequence = u32.GetClipboardSequenceNumber()
            if sequence != before:
                value, sequence = _read_text()
                if value is not None:
                    copied_sequence, result = sequence, value
                    break
        if snapshot and copied_sequence is not None:
            try:
                snapshot.restore(copied_sequence)
            except OSError:
                logging.exception('Zwischenablage konnte nicht wiederhergestellt werden')
        return '' if cancel.is_set() else result.strip()
    except Exception:
        logging.exception('Markierung konnte nicht übernommen werden')
        return ''
    finally:
        if snapshot:
            snapshot.close()
        if hwnd:
            u32.DestroyWindow(hwnd)
        _capture_lock.release()
