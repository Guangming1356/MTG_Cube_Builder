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
    from .resources import system_memory
    return system_memory().get('available')


def configured_heap_mib():
    from .forge import configuration
    try:
        value=configuration().get('heap_mib',2048)
        return value if type(value) is int and value>0 else 2048
    except (OSError,ValueError,KeyError,TypeError):return 2048


def execution_resources(workers=0):
    if type(workers) is not int or not 0 <= workers <= MAX_WORKERS:
        raise ValueError('同时对局数需为 0（自动）至 8')
    cpu = os.cpu_count() or 1
    available = memory_available()
    heap_mib = configured_heap_mib()
    from .resources import capacity
    memory_cap = capacity(dict(available=available),heap_mib=heap_mib)['capacity']
    ceiling = min(MAX_WORKERS, max(1, cpu // 2))
    maximum = min(ceiling, memory_cap)
    automatic = min(4, max(1, cpu // 4), maximum)
    from .tuning import recommendation
    calibrated=recommendation(ceiling) if not workers else None
    if calibrated:automatic=min(maximum,calibrated)
    if workers > maximum:
        raise ValueError(f'当前空闲资源建议最多同时 {maximum} 局；请选择自动或减少同时对局数')
    return dict(requested=workers, workers=workers or automatic, automatic=automatic,
                maximum=maximum, cpu_count=cpu, available_memory_bytes=available,
                heap_mib_per_game=heap_mib, pipeline=True,calibrated=bool(calibrated),
                dynamic=True, ceiling=workers or (calibrated if calibrated else ceiling),
                resource_policy='full-heap-live-memory-1')


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
