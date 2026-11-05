"""Screening and diagnostics tests (ADR-010 phase 2)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from app.pairs import diagnostics, screen
from app.pairs.schemas import QualificationRules, ScanConfig
from tests.pairs_synthetic import cointegrated_pair, independent_walks, log_price_frame


@pytest.fixture(scope="module")
def logp():
    y, x = cointegrated_pair(n=1200, beta=1.2, half_life=12.0, seed=21)
    a, b = independent_walks(n=1200, seed=22)
    return log_price_frame({"NQ=F": y, "ES=F": x, "GC=F": a, "CL=F": b})


class TestCandidatePairs:
    def test_explicit(self) -> None:
        cfg = ScanConfig(mode="explicit", pairs=[("A", "B")])
        assert screen.candidate_pairs(cfg) == [("A", "B")]

    def test_watchlist_defaults_to_the_brief(self) -> None:
        cfg = ScanConfig(mode="watchlist")
        pairs = screen.candidate_pairs(cfg)
        assert ("NQ=F", "ES=F") in pairs and len(pairs) == 10

    def test_watchlist_from_db_overrides_defaults(self) -> None:
        cfg = ScanConfig(mode="watchlist")
        assert screen.candidate_pairs(cfg, watchlist=[("KO", "PEP")]) == [("KO", "PEP")]

    def test_universe_is_ordered_permutations_capped(self) -> None:
        cfg = ScanConfig(mode="universe", tickers=["A", "B", "C"], max_pairs=4)
        pairs = screen.candidate_pairs(cfg)
        assert len(pairs) == 4
        assert ("A", "B") in pairs and ("B", "A") in screen.candidate_pairs(
            ScanConfig(mode="universe", tickers=["A", "B", "C"])
        )

    def test_explicit_requires_pairs_and_distinct_legs(self) -> None:
        with pytest.raises(ValueError):
            ScanConfig(mode="explicit", pairs=[])
        with pytest.raises(ValueError):
            ScanConfig(mode="explicit", pairs=[("A", "A")])


class TestEvaluatePair:
    def test_cointegrated_pair_qualifies(self, logp) -> None:
        cfg = ScanConfig(mode="explicit", pairs=[("NQ=F", "ES=F")], stability_step=5)
        res = screen.evaluate_pair(logp, "NQ=F", "ES=F", cfg)
        assert res is not None
        assert res.qualified, res.reasons
        assert res.beta == pytest.approx(1.2, abs=0.1)
        assert res.half_life is not None and 5 < res.half_life < 30
        assert res.stability_ratio is not None and res.stability_ratio >= 0.8
        assert res.z is not None and res.z_window == min(max(round(2 * res.half_life), 10), 60)
        assert res.pair_name == "NQ/ES"
        assert res.as_of == logp.index[-1].date()
        assert res.beta_tls is not None and res.beta_johansen is not None

    def test_random_walks_do_not_qualify_and_skip_stability(self, logp) -> None:
        cfg = ScanConfig(mode="explicit", pairs=[("GC=F", "CL=F")])
        res = screen.evaluate_pair(logp, "GC=F", "CL=F", cfg)
        assert res is not None
        assert not res.qualified
        assert any("EG p" in r or "half-life" in r or "mean reversion" in r for r in res.reasons)
        assert res.stability_ratio is None  # never paid for

    def test_as_of_cuts_the_window(self, logp) -> None:
        cfg = ScanConfig(mode="explicit", pairs=[("NQ=F", "ES=F")], as_of=date(2020, 6, 30), stability_step=10)
        res = screen.evaluate_pair(logp, "NQ=F", "ES=F", cfg)
        assert res is not None
        assert res.as_of <= date(2020, 6, 30)

    def test_too_short_history_returns_none(self, logp) -> None:
        cfg = ScanConfig(mode="explicit", pairs=[("NQ=F", "ES=F")], as_of=date(2018, 2, 1))
        assert screen.evaluate_pair(logp, "NQ=F", "ES=F", cfg) is None

    def test_unknown_column_returns_none(self, logp) -> None:
        cfg = ScanConfig(mode="explicit", pairs=[("NQ=F", "ZZ")])
        assert screen.evaluate_pair(logp, "NQ=F", "ZZ", cfg) is None

    def test_strict_rules_can_disqualify(self, logp) -> None:
        rules = QualificationRules(half_life_min=1.0, half_life_max=2.0)
        cfg = ScanConfig(mode="explicit", pairs=[("NQ=F", "ES=F")], rules=rules)
        res = screen.evaluate_pair(logp, "NQ=F", "ES=F", cfg)
        assert res is not None and not res.qualified
        assert any("half-life" in r for r in res.reasons)


class TestScanPairs:
    def test_sorts_qualified_first_and_attaches_qvalues(self, logp) -> None:
        cfg = ScanConfig(mode="explicit", pairs=[("GC=F", "CL=F"), ("NQ=F", "ES=F"), ("NQ=F", "ZZ")], stability_step=5)
        results = screen.scan_pairs(logp, cfg.pairs, cfg, roll_gaps={"NQ=F": 3}, quality_flags={"ES=F": ["extreme_move"]})
        assert [r.pair_name for r in results][0] == "NQ/ES"
        assert len(results) == 2  # unknown ticker silently skipped
        assert all(r.eg_qvalue is not None for r in results)
        assert results[0].eg_qvalue >= results[0].eg_pvalue
        assert results[0].roll_gap_days == 3 and results[0].quality_flags == ["extreme_move"]


class TestDiagnostics:
    def test_rolling_series_is_strictly_backward_looking(self, logp) -> None:
        y = logp["NQ=F"].to_numpy()
        x = logp["ES=F"].to_numpy()
        base = diagnostics.rolling_series(y, x, logp.index, formation_window=300, z_window_min=10, z_window_max=60)
        # Perturb everything after T; nothing up to T may change.
        cut = 700
        y2 = y.copy()
        x2 = x.copy()
        rng = np.random.default_rng(0)
        y2[cut + 1 :] = rng.normal(size=len(y) - cut - 1)
        x2[cut + 1 :] = rng.normal(size=len(x) - cut - 1)
        pert = diagnostics.rolling_series(y2, x2, logp.index, formation_window=300, z_window_min=10, z_window_max=60)
        np.testing.assert_array_equal(base.zscore[: cut + 1], pert.zscore[: cut + 1])
        np.testing.assert_array_equal(base.beta[: cut + 1], pert.beta[: cut + 1])
        np.testing.assert_array_equal(base.spread[: cut + 1], pert.spread[: cut + 1])
        assert np.isnan(base.zscore[:300]).all()
        assert np.isfinite(base.zscore[400:]).mean() > 0.95

    def test_forward_buckets_show_mean_reversion(self, logp) -> None:
        y = logp["NQ=F"].to_numpy()
        x = logp["ES=F"].to_numpy()
        rs = diagnostics.rolling_series(y, x, logp.index, formation_window=300, z_window_min=10, z_window_max=60)
        buckets = diagnostics.forward_buckets(rs.spread, rs.zscore, horizons=(10,), min_count=3)
        assert buckets
        extreme = [b for b in buckets if b.bucket in ("[2, 2.5)", "[-2.5, -2)")]
        assert len(extreme) == 2, [b.bucket for b in buckets]
        # In a true OU spread, |z| ≥ 2 must revert toward the mean more often than not.
        assert all(b.hit_rate > 0.6 for b in extreme)
        assert all(b.count >= 20 for b in extreme)
        pos = [b for b in buckets if b.z_low >= 2.0]
        assert all(b.mean < 0 for b in pos)

    def test_forward_buckets_respect_min_count_and_short_series(self) -> None:
        assert diagnostics.forward_buckets(np.zeros(5), np.zeros(5), horizons=(10,)) == []

    def test_to_list_nan_safe(self) -> None:
        assert diagnostics.to_list(np.array([1.0, np.nan])) == [1.0, None]
