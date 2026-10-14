"""A Windows Job Object around a sandboxed command's processes (ADR-0004, L2).

The command is created suspended, assigned to the job, then resumed, so nothing it starts can
run outside the job: children join their parent's job by default (AssignProcessToJobObject,
Microsoft Learn). The job kills every process when its last handle closes, caps the processes
alive at once and the memory they commit together, and keeps a crashing process from waiting on
an error dialog. Resuming uses the documented Toolhelp32 thread snapshot and ``ResumeThread``.
Nested jobs (Windows 8 and later) let this work when Repro itself runs inside a job.
"""

import sys
from typing import Any

from repro.sandbox.limits import Limits

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # Constants from the Win32 documentation (winnt.h, jobapi2.h, tlhelp32.h).
    _JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
    _JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
    _JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_SET_QUOTA = 0x0100
    _THREAD_SUSPEND_RESUME = 0x0002
    _TH32CS_SNAPTHREAD = 0x00000004
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    _RESUME_FAILED = 0xFFFFFFFF

    class _BasicLimits(ctypes.Structure):
        _fields_ = (
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        )

    class _IoCounters(ctypes.Structure):
        _fields_ = tuple(
            (name, ctypes.c_uint64)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        )

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = (
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        )

    class _Accounting(ctypes.Structure):
        _fields_ = (
            ("TotalUserTime", ctypes.c_int64),
            ("TotalKernelTime", ctypes.c_int64),
            ("ThisPeriodTotalUserTime", ctypes.c_int64),
            ("ThisPeriodTotalKernelTime", ctypes.c_int64),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        )

    class _ThreadEntry(ctypes.Structure):
        _fields_ = (
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", wintypes.LONG),
            ("tpDeltaPri", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
        )

    def _api(name: str, restype: Any, *argtypes: Any) -> Any:
        function = getattr(_kernel32, name)
        function.restype = restype
        function.argtypes = argtypes
        return function

    _CreateJobObjectW = _api("CreateJobObjectW", wintypes.HANDLE, ctypes.c_void_p, wintypes.LPCWSTR)
    _SetInformationJobObject = _api(
        "SetInformationJobObject",
        wintypes.BOOL,
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    _QueryInformationJobObject = _api(
        "QueryInformationJobObject",
        wintypes.BOOL,
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
    )
    _AssignProcessToJobObject = _api(
        "AssignProcessToJobObject", wintypes.BOOL, wintypes.HANDLE, wintypes.HANDLE
    )
    _TerminateJobObject = _api("TerminateJobObject", wintypes.BOOL, wintypes.HANDLE, wintypes.UINT)
    _OpenProcess = _api(
        "OpenProcess", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD
    )
    _OpenThread = _api("OpenThread", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _ResumeThread = _api("ResumeThread", wintypes.DWORD, wintypes.HANDLE)
    _CloseHandle = _api("CloseHandle", wintypes.BOOL, wintypes.HANDLE)
    _CreateToolhelp32Snapshot = _api(
        "CreateToolhelp32Snapshot", wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD
    )
    _Thread32First = _api("Thread32First", wintypes.BOOL, wintypes.HANDLE, ctypes.c_void_p)
    _Thread32Next = _api("Thread32Next", wintypes.BOOL, wintypes.HANDLE, ctypes.c_void_p)

    def _check(ok: object, what: str) -> None:
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error(), f"{what} failed")

    def _resume(pid: int) -> int:
        """Resumes every thread of a suspended process; the number resumed."""
        snapshot = _CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
        if snapshot in (None, _INVALID_HANDLE_VALUE):
            raise ctypes.WinError(ctypes.get_last_error(), "CreateToolhelp32Snapshot failed")
        resumed = 0
        try:
            entry = _ThreadEntry()
            entry.dwSize = ctypes.sizeof(_ThreadEntry)
            more = _Thread32First(snapshot, ctypes.byref(entry))
            while more:
                if entry.th32OwnerProcessID == pid:
                    thread = _OpenThread(_THREAD_SUSPEND_RESUME, False, entry.th32ThreadID)
                    _check(thread, "OpenThread")
                    try:
                        if _ResumeThread(thread) == _RESUME_FAILED:
                            raise ctypes.WinError(ctypes.get_last_error(), "ResumeThread failed")
                        resumed += 1
                    finally:
                        _CloseHandle(thread)
                more = _Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            _CloseHandle(snapshot)
        return resumed

    class Job:
        """A Job Object with the sandbox's limits. Closing it kills what is left in it."""

        def __init__(self, limits: Limits) -> None:
            handle = _CreateJobObjectW(None, None)
            _check(handle, "CreateJobObjectW")
            self._handle: int | None = handle
            info = _ExtendedLimits()
            info.BasicLimitInformation.LimitFlags = (
                _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                | _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
                | _JOB_OBJECT_LIMIT_JOB_MEMORY
                | _JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
            )
            info.BasicLimitInformation.ActiveProcessLimit = limits.processes
            info.JobMemoryLimit = limits.memory_bytes
            try:
                _check(
                    _SetInformationJobObject(
                        handle,
                        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                        ctypes.byref(info),
                        ctypes.sizeof(info),
                    ),
                    "SetInformationJobObject",
                )
            except BaseException:
                self.close()
                raise

        def adopt_suspended(self, pid: int) -> None:
            """Assigns a process created with CREATE_SUSPENDED to the job, then resumes it."""
            process = _OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
            _check(process, "OpenProcess")
            try:
                _check(_AssignProcessToJobObject(self._handle, process), "AssignProcessToJobObject")
            finally:
                _CloseHandle(process)
            if _resume(pid) == 0:
                raise OSError(f"no thread of process {pid} to resume")

        def active_processes(self) -> int:
            accounting = _Accounting()
            _check(
                _QueryInformationJobObject(
                    self._handle,
                    _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
                    ctypes.byref(accounting),
                    ctypes.sizeof(accounting),
                    None,
                ),
                "QueryInformationJobObject",
            )
            return int(accounting.ActiveProcesses)

        def peak_memory(self) -> int:
            """The most memory the job's processes committed at once, in bytes."""
            info = _ExtendedLimits()
            _check(
                _QueryInformationJobObject(
                    self._handle,
                    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                    ctypes.byref(info),
                    ctypes.sizeof(info),
                    None,
                ),
                "QueryInformationJobObject",
            )
            return int(info.PeakJobMemoryUsed)

        def terminate(self) -> None:
            if self._handle is not None:
                _TerminateJobObject(self._handle, 1)

        def close(self) -> None:
            """Closes the job: with kill-on-close, every process still in it ends."""
            if self._handle is not None:
                _CloseHandle(self._handle)
                self._handle = None
