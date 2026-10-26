"""Windows session ownership and foreground-safe positioning. No network IPC."""
import ctypes
from ctypes import wintypes
import hashlib
from pathlib import Path

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)
k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
k32.CreateMutexW.restype = wintypes.HANDLE
k32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
k32.CreateEventW.restype = wintypes.HANDLE
k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
k32.WaitForSingleObject.restype = wintypes.DWORD
k32.SetEvent.argtypes = [wintypes.HANDLE]
k32.CloseHandle.argtypes = [wintypes.HANDLE]


class SingleInstance:
    def __init__(self):
        key = hashlib.sha256(str(Path(__file__).resolve().parent).lower().encode()).hexdigest()[:20]
        self.mutex = k32.CreateMutexW(None, False, "Local\\TTSReader-" + key)
        if not self.mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        self.primary = ctypes.get_last_error() != 183
        self.event = k32.CreateEventW(None, False, False, "Local\\TTSReaderShow-" + key)
        if not self.event:
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def request_show(self):
        k32.SetEvent(self.event)

    def show_requested(self):
        return k32.WaitForSingleObject(self.event, 0) == 0

    def close(self):
        for name in ("event", "mutex"):
            handle = getattr(self, name, None)
            if handle:
                k32.CloseHandle(handle)
                setattr(self, name, None)


u32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
u32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
dwm = ctypes.WinDLL("dwmapi")
dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]


def prevent_activation(hwnd):
    """Keep floating controls from stealing document focus."""
    style = u32.GetWindowLongW(hwnd, -20)
    # Tool window, no activation: clicking the player must not focus away from a document.
    u32.SetWindowLongW(hwnd, -20, style | 0x80 | 0x08000000)
    return hwnd


def set_dark_title_bar(hwnd, dark):
    """Match the native title bar to the app theme (DWMWA_USE_IMMERSIVE_DARK_MODE)."""
    value = ctypes.c_int(1 if dark else 0)
    dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
