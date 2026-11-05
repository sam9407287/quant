"""Statistics tests (ADR-010 phase 2) on synthetic series with known answers."""

from __future__ import annotations

import numpy as np
import pytest

from app.pairs import stats
from tests.pairs_synthetic import cointegrated_pair, independent_walks


class TestHedgeRatio:
    def test_ols_recovers_known_beta(self) -> None:
        y, x = cointegrated_pair(beta=1.3, alpha=0.2)
        fit = stats.ols_hedge(y, x)
        assert fit.beta == pytest.approx(1.3, abs=0.03)
        assert fit.alpha == pytest.approx(0.2, abs=0.2)
        assert fit.method == "ols"
        assert len(fit.spread) == len(y)

    def test_tls_is_symmetric_in_the_legs(self) -> None:
        y, x = cointegrated_pair(beta=1.3, seed=3)
        b_yx = stats.tls_hedge(y, x).beta
        b_xy = stats.tls_hedge(x, y).beta
        assert b_yx * b_xy == pytest.approx(1.0, rel=1e-6)

    def test_ols_is_not_symmetric_but_close_for_tight_pairs(self) -> None:
        y, x = cointegrated_pair(beta=1.3, spread_sigma=0.002, seed=4)
        assert stats.ols_hedge(y, x).beta * stats.ols_hedge(x, y).beta == pytest.approx(1.0, abs=0.02)

    def test_input_validation(self) -> None:
        with pytest.raises(ValueError):
            stats.ols_hedge(np.array([1.0, 2.0]), np.array([1.0, 2.0, 3.0]))
        with pytest.raises(ValueError):
            stats.ols_hedge(np.array([1.0, np.nan, 3.0]), np.array([1.0, 2.0, 3.0]))


class TestCointegrationTests:
    def test_cointegrated_pair_passes_every_test(self) -> None:
        y, x = cointegrated_pair()
        ev = stats.cointegration_evidence(y, x)
        assert ev.eg_pvalue < 0.01
        assert ev.eg_pvalue_reverse < 0.01
        assert ev.adf_pvalue < 0.01
        assert ev.johansen_pass
        assert ev.hurst is not None and ev.hurst < 0.5

    def test_independent_walks_false_positive_rate_near_alpha(self) -> None:
        rejections = 0
        trials = 40
        for seed in range(trials):
            y, x = independent_walks(n=600, seed=100 + seed)
            if stats.engle_granger_pvalue(y, x) < 0.05:
                rejections += 1
        # Binomial(40, 0.05): P(>6) < 1%. Anything above that means the
        # test is anti-conservative and the whole screen is suspect.
        assert rejections <= 6

    def test_johansen_hedge_close_to_ols(self) -> None:
        y, x = cointegrated_pair(beta=0.8, seed=5)
        bj = stats.johansen_hedge(y, x)
        assert bj is not None
        assert bj == pytest.approx(0.8, abs=0.1)

    def test_hurst_returns_none_on_short_series(self) -> None:
        assert stats.hurst_exponent(np.arange(30, dtype=float)) is None


class TestHalfLife:
    def test_recovers_known_half_life(self) -> None:
        y, x = cointegrated_pair(half_life=10.0, n=3000, seed=6)
        spread = stats.ols_hedge(y, x).spread
        hl = stats.half_life(spread)
        assert hl.lam < 0
        assert hl.half_life is not None
        assert hl.half_life == pytest.approx(10.0, rel=0.35)

    def test_random_walk_has_no_half_life_or_a_huge_one(self) -> None:
        y, _ = independent_walks(seed=9)
        hl = stats.half_life(y)
        assert hl.half_life is None or hl.half_life > 100

    def test_confidence_interval_brackets_point_estimate(self) -> None:
        y, x = cointegrated_pair(half_life=8.0, n=1500, seed=7)
        spread = stats.ols_hedge(y, x).spread
        hl = stats.half_life_with_ci(spread, n_boot=100)
        assert hl.half_life is not None and hl.ci_low is not None and hl.ci_high is not None
        assert hl.ci_low <= hl.ci_high
        assert hl.ci_low < 16 and hl.ci_high > 4

    def test_short_series_is_not_estimable(self) -> None:
        hl = stats.half_life(np.array([1.0, 2.0, 3.0]))
        assert hl.half_life is None and np.isnan(hl.lam)


class TestZScore:
    def test_window_rule(self) -> None:
        assert stats.zscore_window(8.4) == 17
        assert stats.zscore_window(2.0) == 10
        assert stats.zscore_window(100.0) == 60
        assert stats.zscore_window(None) == 60
        assert stats.zscore_window(8.0, lower=20, upper=40) == 20

    def test_rolling_z_matches_pandas(self) -> None:
        import pandas as pd

        rng = np.random.default_rng(0)
        s = rng.normal(size=200)
        z = stats.rolling_zscore(s, 20)
        ref = (pd.Series(s) - pd.Series(s).rolling(20).mean()) / pd.Series(s).rolling(20).std(ddof=1)
        np.testing.assert_allclose(z[19:], ref.to_numpy()[19:], rtol=1e-9, atol=1e-9)
        assert np.isnan(z[:19]).all()

    def test_rolling_z_degenerate_cases(self) -> None:
        assert np.isnan(stats.rolling_zscore(np.ones(50), 10)).all()  # zero std
        assert np.isnan(stats.rolling_zscore(np.arange(5.0), 10)).all()  # too short

    def test_frozen_z(self) -> None:
        assert stats.frozen_zscore(1.5, 1.0, 0.25) == 2.0
        assert np.isnan(stats.frozen_zscore(1.5, 1.0, 0.0))

    def test_ewma_z_has_values_after_warmup(self) -> None:
        rng = np.random.default_rng(1)
        z = stats.ewma_zscore(rng.normal(size=100), 20)
        assert np.isnan(z[:19]).all()
        assert np.isfinite(z[25:]).all()


class TestBenjaminiHochberg:
    def test_known_example(self) -> None:
        p = np.array([0.01, 0.04, 0.03, 0.20])
        q = stats.benjamini_hochberg(p)
        # sorted: .01,.03,.04,.20 → raw .04,.06,.0533,.20 → monotone .04,.0533,.0533,.20
        np.testing.assert_allclose(q, [0.04, 0.0533333, 0.0533333, 0.20], rtol=1e-5)

    def test_nan_preserved_and_excluded_from_m(self) -> None:
        q = stats.benjamini_hochberg(np.array([0.01, np.nan, 0.02]))
        assert np.isnan(q[1])
        np.testing.assert_allclose(q[[0, 2]], [0.02, 0.02])

    def test_all_nan(self) -> None:
        assert np.isnan(stats.benjamini_hochberg(np.array([np.nan, np.nan]))).all()


class TestRollingStability:
    def test_cointegrated_pair_is_stable(self) -> None:
        y, x = cointegrated_pair(n=800, seed=11)
        pv = stats.rolling_eg_pvalues(y, x, window=504, lookback=30, step=3)
        finite = pv[np.isfinite(pv)]
        assert len(finite) == 30  # stepped values are forward-filled
        assert (finite < 0.05).mean() >= 0.8

    def test_window_that_does_not_fit_is_nan(self) -> None:
        y, x = cointegrated_pair(n=300, seed=12)
        pv = stats.rolling_eg_pvalues(y, x, window=504, lookback=10)
        assert np.isnan(pv).all()

    def test_rolling_beta_and_cv(self) -> None:
        y, x = cointegrated_pair(n=800, beta=1.1, seed=13)
        betas = stats.rolling_beta(y, x, window=400, lookback=20)
        assert np.isfinite(betas).all()
        assert stats.coefficient_of_variation(betas) < 0.1
        assert np.isnan(stats.coefficient_of_variation(np.array([np.nan, np.nan])))
