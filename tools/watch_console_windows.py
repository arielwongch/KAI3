r"""Record Windows console popups and their process ancestry without spawning shells.

Run from an existing terminal:
    venv\Scripts\python.exe tools\watch_console_windows.py --seconds 300

The JSONL report contains executable names, PIDs, and window titles, never command
lines or environment variables. Press Ctrl+C to stop early.
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import time


CONSOLE_NAMES = {'powershell.exe', 'pwsh.exe', 'cmd.exe', 'conhost.exe',
                 'openconsole.exe', 'windowsterminal.exe', 'python.exe', 'pythonw.exe'}


class ProcessEntry(ctypes.Structure):
    _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
                ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG),
                ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR * 260)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=300)
    parser.add_argument('--output', type=Path, default=Path('instance/console-popups.jsonl'))
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('This diagnostic requires Windows.')
    if args.seconds <= 0:
        parser.error('--seconds must be positive.')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    previous_pids = None
    previous_windows = set()
    deadline = time.monotonic() + args.seconds
    message = f'Watching console windows; report: {args.output.resolve()}'
    print(message.encode(sys.stdout.encoding or 'utf-8', errors='backslashreplace')
          .decode(sys.stdout.encoding or 'utf-8'), flush=True)
    with args.output.open('a', encoding='utf-8') as report:
        def record(event, **fields):
            report.write(json.dumps(dict(time=time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                                         event=event, **fields), ensure_ascii=False) + '\n')
            report.flush()

        record('watch_started', watcher_pid=os.getpid())
        try:
            while time.monotonic() < deadline:
                processes = {}
                snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
                if snapshot == ctypes.c_void_p(-1).value:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    entry = ProcessEntry()
                    entry.dwSize = ctypes.sizeof(entry)
                    more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
                    while more:
                        processes[entry.th32ProcessID] = dict(pid=entry.th32ProcessID,
                            parent_pid=entry.th32ParentProcessID, exe=entry.szExeFile)
                        more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
                finally:
                    kernel.CloseHandle(snapshot)

                def ancestry(pid):
                    chain, seen = [], set()
                    while pid in processes and pid not in seen:
                        seen.add(pid)
                        chain.append(processes[pid])
                        pid = processes[pid]['parent_pid']
                    return chain

                if previous_pids is not None:
                    for pid in processes.keys() - previous_pids:
                        if processes[pid]['exe'].lower() in CONSOLE_NAMES:
                            record('console_process_started', ancestry=ancestry(pid))
                windows = set()

                @callback_type
                def visit(hwnd, _):
                    if user.IsWindowVisible(hwnd):
                        pid = wintypes.DWORD()
                        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                        if processes.get(pid.value, {}).get('exe', '').lower() in CONSOLE_NAMES:
                            identity = (hwnd, pid.value)
                            windows.add(identity)
                            if identity not in previous_windows:
                                title = ctypes.create_unicode_buffer(1024)
                                user.GetWindowTextW(hwnd, title, len(title))
                                record('visible_console_window', existing=previous_pids is None,
                                       title=title.value, ancestry=ancestry(pid.value))
                    return True

                if not user.EnumWindows(visit, 0):
                    raise ctypes.WinError(ctypes.get_last_error())
                previous_pids, previous_windows = set(processes), windows
                time.sleep(.1)
        except KeyboardInterrupt:
            pass
        finally:
            record('watch_stopped')


if __name__ == '__main__':
    main()
