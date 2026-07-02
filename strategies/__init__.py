from . import ma_crossover, rsi_strategy, momentum

REGISTRY = {
    ma_crossover.NAME: ma_crossover,
    rsi_strategy.NAME: rsi_strategy,
    momentum.NAME: momentum,
}


def get_strategy(name):
    if name not in REGISTRY:
        raise ValueError(f"Unknown strategy '{name}'. Available: {list(REGISTRY)}")
    return REGISTRY[name]


def list_strategies():
    return [
        {"name": mod.NAME, "label": mod.LABEL, "default_params": mod.DEFAULT_PARAMS}
        for mod in REGISTRY.values()
    ]
