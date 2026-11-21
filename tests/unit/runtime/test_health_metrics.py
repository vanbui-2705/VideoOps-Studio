from core.runtime.health import HealthService, MetricsRegistry


def test_health_service_runs_only_registered_local_checks():
    calls = []
    health = HealthService(
        {
            "database": lambda: calls.append("database") or True,
            "disk": lambda: calls.append("disk") or True,
        }
    )

    report = health.check()

    assert report.ready is True
    assert calls == ["database", "disk"]


def test_metrics_registry_rejects_high_cardinality_labels():
    metrics = MetricsRegistry()
    metrics.increment(
        "worker_failures_total", {"phase": "PUBLISH", "platform": "YOUTUBE"}
    )

    assert metrics.snapshot()[0].value == 1

    try:
        metrics.increment("worker_failures_total", {"job_id": "job-1"})
    except ValueError as exc:
        assert "label" in str(exc)
    else:
        raise AssertionError("job_id label must be rejected")
