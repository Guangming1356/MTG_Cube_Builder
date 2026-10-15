"""Declared experiment budgets and bounded local execution resources."""
import os

PROFILES = {
    'quick': dict(label='快速排错', training_pods=10, holdout_pods=10,
                  ranking_pods=100, structural_pods=100, max_swaps=10, alternatives=80),
    'standard': dict(label='标准改进', training_pods=30, holdout_pods=30,
                     ranking_pods=200, structural_pods=300, max_swaps=24, alternatives=120),
    'deep': dict(label='深入评估', training_pods=100, holdout_pods=100,
                 ranking_pods=500, structural_pods=1000, max_swaps=48, alternatives=240),
}
MAX_WORKERS = 8
MAX_PODS = 120


def memory_available():
    try:
        if os.name == 'nt':
            import ctypes
            class Memory(ctypes.Structure):
                _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                    (name, ctypes.c_ulonglong) for name in
                    ('total', 'available', 'page_total', 'page_available', 'virtual_total', 'virtual_available', 'extended')]
            value = Memory(); value.length = ctypes.sizeof(value)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
                return value.available
        return os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
    except (AttributeError, OSError, ValueError):
        return None


def execution_resources(workers=0):
    if type(workers) is not int or not 0 <= workers <= MAX_WORKERS:
        raise ValueError('同时对局数需为 0（自动）至 8')
    cpu = os.cpu_count() or 1
    available = memory_available()
    # Each JVM has a 2 GiB heap, plus native memory. Reserve room for the UI/OS.
    memory_cap = max(1, int((available / 2**30 - 3) // 2.75)) if available else 2
    maximum = min(MAX_WORKERS, max(1, cpu // 2), memory_cap)
    automatic = min(4, max(1, cpu // 4), maximum)
    from .tuning import recommendation
    calibrated=recommendation(maximum) if not workers else None
    if calibrated:automatic=calibrated
    if workers > maximum:
        raise ValueError(f'当前空闲资源建议最多同时 {maximum} 局；请选择自动或减少同时对局数')
    return dict(requested=workers, workers=workers or automatic, automatic=automatic,
                maximum=maximum, cpu_count=cpu, available_memory_bytes=available,
                heap_mib_per_game=2048, pipeline=True,calibrated=bool(calibrated))


def experiment_budget(profile='standard', training_pods=None, max_swaps=None, cube_size=600):
    if profile not in PROFILES:
        raise ValueError('评估档位需为 quick、standard 或 deep')
    value = dict(PROFILES[profile], profile=profile)
    if training_pods is not None:
        if type(training_pods) is not int or not 10 <= training_pods <= MAX_PODS or training_pods % 10:
            raise ValueError('训练桌数需为 10–120，且为 10 的倍数，以均匀覆盖十个双色')
        value['training_pods'] = training_pods
    limit = min(60, max(1, cube_size // 10))
    if max_swaps is not None:
        if type(max_swaps) is not int or not 1 <= max_swaps <= limit:
            raise ValueError(f'单轮替换上限需为 1–{limit} 张（最多为 Cube 的 10%）')
        value['max_swaps'] = max_swaps
    else:
        value['max_swaps'] = min(value['max_swaps'], limit)
    value['native_games_before_cross'] = 3 * (value['training_pods'] + 2 * value['holdout_pods'])
    value['maximum_cross_games'] = 9 * value['holdout_pods']
    return value
