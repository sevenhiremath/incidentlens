import pytest

from benchmarks.stats import aggregate, percentile, summarize


def test_percentiles_use_nearest_rank_on_sorted_samples():
    assert percentile(list(range(100, 0, -1)), 0.95) == 95
    assert percentile([12], 0.95) == 12
    with pytest.raises(ValueError):
        percentile([], 0.95)


def test_summary_keeps_status_counts_and_full_request_count():
    result = summarize([1, 2, 3, 4], 2, [201, 200, 201, 200])
    assert result["requests"] == 4
    assert result["requests_per_second"] == 2
    assert result["status_counts"] == {"200": 2, "201": 2}
    assert result["p95_ms"] == 4


def test_aggregate_uses_median_of_runs_not_best_result():
    runs = [{"read": summarize([value] * 10, 1, [200] * 10)} for value in [5, 1, 9]]
    result = aggregate(runs, "read")
    assert result["median_p95_ms"] == 5
    assert result["p95_range_ms"] == [1, 9]
    assert result["total_measured_requests"] == 30
