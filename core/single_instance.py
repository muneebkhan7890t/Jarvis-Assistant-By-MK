"""Prevent two Windows assistant processes from competing for audio and job state."""
import sys

_handle = None


def acquire():
    global _handle
    if sys.platform != 'win32':
        return True
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateMutexW(None, False, 'Local\\MarkLIII_Assistant')
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(handle)
        return False
    _handle = handle  # Retained until the process exits.
    return True
