"""Local readiness checks and bounded-cardinality in-process metrics."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HealthReport:
    ready: bool
    checks: dict[str, bool]


class HealthService:
    def __init__(self, checks: Mapping[str, Callable[[], bool]]) -> None:
        self._checks = dict(checks)

    def check(self) -> HealthReport:
        results: dict[str, bool] = {}
        for name, check in self._checks.items():
            try:
                results[name] = bool(check())
            except Exception:  # noqa: BLE001 - health surfaces no exception details
                results[name] = False
        return HealthReport(all(results.values()), results)


@dataclass(frozen=True, slots=True)
class MetricSample:
    name: str
    labels: tuple[tuple[str, str], ...]
    value: int


class MetricsRegistry:
    _LABELS = frozenset({"phase", "platform", "kind", "result"})

    def __init__(self) -> None:
        self._values: dict[tuple[str, tuple[tuple[str, str], ...]], int] = {}

    def increment(self, name: str, labels: Mapping[str, str] | None = None) -> None:
        normalized = tuple(sorted((labels or {}).items()))
        if not name.endswith("_total") or any(
            key not in self._LABELS for key, _ in normalized
        ):
            raise ValueError("Metric name or label is not allowlisted")
        key = (name, normalized)
        self._values[key] = self._values.get(key, 0) + 1

    def snapshot(self) -> tuple[MetricSample, ...]:
        return tuple(
            MetricSample(name, labels, value)
            for (name, labels), value in sorted(self._values.items())
        )
