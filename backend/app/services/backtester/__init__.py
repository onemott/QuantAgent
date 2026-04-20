"""
Backtester package exports.

Use lazy imports here to avoid circular import chains such as:
`metrics_calculator -> backtester.annualization -> backtester.__init__ -> vectorized -> metrics_calculator`.
"""

__all__ = [
    "VectorizedBacktester",
    "EventDrivenBacktester",
    "GridOptimizer",
    "OptunaOptimizer",
]


def __getattr__(name: str):
    if name == "VectorizedBacktester":
        from .vectorized import VectorizedBacktester

        return VectorizedBacktester
    if name == "EventDrivenBacktester":
        from .event_driven import EventDrivenBacktester

        return EventDrivenBacktester
    if name == "GridOptimizer":
        from .optimizer import GridOptimizer

        return GridOptimizer
    if name == "OptunaOptimizer":
        from .optimizer import OptunaOptimizer

        return OptunaOptimizer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
