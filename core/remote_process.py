"""A hidden Windows process tree owned by a kill-on-close Job Object.

Project code still runs with the user's account permissions: this is lifecycle
control, not an execution sandbox. Assign the suspended process before resuming.
"""
import os
import subprocess
import threading

_spawn_lock = threading.Lock()


class OwnedProcess:
    def __init__(self, argv, cwd):
        if os.name != "nt":
            raise RuntimeError("Reviewed remote project execution currently requires Windows")
        import win32api
        import win32con
        import win32file
        import win32job
        import win32pipe
        import win32process
        import pywintypes
        self.process = self.job = self.reader = None
        thread = writer = stdin = None
        try:
            self.job = win32job.CreateJobObject(None, "")
            limits = win32job.QueryInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation)
            limits["BasicLimitInformation"]["LimitFlags"] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation, limits)
            attributes = pywintypes.SECURITY_ATTRIBUTES()
            attributes.bInheritHandle = True
            # Keep inherited pipe handles from leaking between this runner's launches.
            with _spawn_lock:
                self.reader, writer = win32pipe.CreatePipe(attributes, 0)
                win32api.SetHandleInformation(self.reader, win32con.HANDLE_FLAG_INHERIT, 0)
                stdin = win32file.CreateFile("NUL", win32con.GENERIC_READ,
                                            win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                                            attributes, win32con.OPEN_EXISTING, 0, None)
                startup = win32process.STARTUPINFO()
                startup.dwFlags = win32process.STARTF_USESTDHANDLES | win32process.STARTF_USESHOWWINDOW
                startup.wShowWindow = win32con.SW_HIDE
                startup.hStdInput, startup.hStdOutput, startup.hStdError = stdin, writer, writer
                self.process, thread, self.pid, _ = win32process.CreateProcess(
                    argv[0], subprocess.list2cmdline(argv), None, None, True,
                    win32process.CREATE_SUSPENDED | win32process.CREATE_NO_WINDOW,
                    None, cwd, startup)
                writer.Close()
                writer = None
                stdin.Close()
                stdin = None
            win32job.AssignProcessToJobObject(self.job, self.process)
            win32process.ResumeThread(thread)
        except Exception:
            if self.process:
                win32process.TerminateProcess(self.process, 1)
            self.close()
            raise
        finally:
            for handle in (thread, writer, stdin):
                if handle:
                    handle.Close()

    def poll(self):
        import win32event
        import win32process
        if win32event.WaitForSingleObject(self.process, 0) == win32event.WAIT_TIMEOUT:
            return None
        return win32process.GetExitCodeProcess(self.process)

    def chunks(self):
        import win32file
        import pywintypes
        try:
            while True:
                _result, data = win32file.ReadFile(self.reader, 4096)
                if not data:
                    return
                yield data
        except pywintypes.error as exc:
            if exc.winerror not in (6, 109, 995):
                raise

    def wait(self, timeout=3):
        import win32event
        if win32event.WaitForSingleObject(self.process, int(timeout * 1000)) == win32event.WAIT_TIMEOUT:
            return None
        return self.poll()

    def terminate(self):
        import win32job
        if self.job:
            win32job.TerminateJobObject(self.job, 1)

    def close(self):
        # Closing the job first also terminates any child still holding the pipe.
        for attr in ("job", "process", "reader"):
            handle = getattr(self, attr, None)
            if handle:
                handle.Close()
                setattr(self, attr, None)
