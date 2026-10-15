"""Read-only memory measurements. Only explicitly owned engine PIDs are inspected."""
import ctypes
import os
from pathlib import Path

MIB = 2**20
RESERVE_BYTES = 1536 * MIB
NATIVE_ALLOWANCE_MIB = 768


def system_memory():
    try:
        if os.name == 'nt':
            class Memory(ctypes.Structure):
                _fields_ = [('length', ctypes.c_uint32), ('load', ctypes.c_uint32)] + [
                    (name, ctypes.c_uint64) for name in
                    ('total', 'available', 'commit_limit', 'commit_available', 'virtual_total', 'virtual_available', 'extended')]
            value = Memory(); value.length = ctypes.sizeof(value)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
                return dict(available=value.available, total=value.total,
                            commit_available=value.commit_available, load=value.load)
        return dict(available=os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE'))
    except (AttributeError, OSError, ValueError):
        pass
    return {}


def process_memory(pid):
    try:
        if os.name == 'nt':
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
                    (name, ctypes.c_size_t) for name in ('peak_working_set', 'working_set',
                    'peak_paged', 'paged', 'peak_nonpaged', 'nonpaged', 'commit', 'peak_commit', 'private_bytes')]
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            psapi = ctypes.WinDLL('psapi', use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
            if not handle:return None
            try:
                value = Counters(); value.cb = ctypes.sizeof(value)
                if psapi.GetProcessMemoryInfo(handle, ctypes.byref(value), value.cb):
                    return {k: int(getattr(value, k)) for k in
                            ('working_set', 'peak_working_set', 'private_bytes', 'peak_commit')}
            finally:kernel.CloseHandle(handle)
        else:
            pages = [int(v) for v in Path(f'/proc/{pid}/statm').read_text().split()]
            # Exclude shared pages rather than crediting them to every JVM.
            return dict(working_set=max(0, pages[1]-pages[2])*os.sysconf('SC_PAGE_SIZE'))
    except (AttributeError, OSError, ValueError, IndexError):
        pass
    return None


def capacity(snapshot, engines=(), heap_mib=2048, ceiling=8):
    """Budget the full heap plus native allowance, even for a currently small JVM.

    Existing owned memory gets conservative credit because it is already absent
    from available RAM. Shared working-set pages receive a 20% haircut. Commit
    headroom is checked separately; unknown memory never enables an expansion.
    """
    budget = max((heap_mib + NATIVE_ALLOWANCE_MIB) * MIB,
                 int(max((max(e.get('peak_commit', 0), e.get('peak_working_set', 0)) for e in engines),default=0)*1.15))
    available = snapshot.get('available')
    if available is None:return dict(capacity=1, reason='memory_unknown', per_engine_bytes=budget)
    physical_credit = sum(min(e.get('working_set', 0), e.get('private_bytes', e.get('working_set', 0)), budget)*.8 for e in engines)
    physical = int((available + physical_credit - RESERVE_BYTES)//budget)
    commit_available = snapshot.get('commit_available')
    commit = ceiling
    if commit_available is not None:
        credit = sum(min(e.get('private_bytes', 0), budget) for e in engines)
        commit = int((commit_available + credit - RESERVE_BYTES)//budget)
    value = max(1, min(ceiling, physical, commit))
    reason = 'commit_pressure' if commit < min(physical, ceiling) else 'memory_budget' if physical < ceiling else 'cpu_limit'
    return dict(capacity=value, reason=reason, available_memory_bytes=available,
                commit_available_bytes=commit_available, owned_engines=len(engines),
                owned_working_set_bytes=sum(e.get('working_set', 0) for e in engines),
                per_engine_bytes=budget, reserve_bytes=RESERVE_BYTES)
