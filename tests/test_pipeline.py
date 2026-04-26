"""Unit tests for the data ingestion pipeline (no DB required)."""

from __future__ import annotations

import pandas as pd
import pytest

from fetcher.pipeline import flag_anomalies, validate


def _make_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


class TestValidate:
    def test_raises_on_missing_columns(self) -> None:
        df = pd.DataFrame({"ts": [], "open": []})
        with pytest.raises(ValueError, match="missing required columns"):
            validate(df)

    def test_drops_null_rows(self) -> None:
        df = _make_df([
            {"ts": "2024-01-01 09:00", "open": 18000, "high": 18100,
             "low": 17900, "close": None, "volume": 1000},
            {"ts": "2024-01-01 09:01", "open": 18010, "high": 18110,
             "low": 17910, "close": 18050, "volume": 1100},
        ])
        result = validate(df)
        assert len(result) == 1
        assert result.iloc[0]["open"] == 18010

    def test_drops_zero_volume_rows(self) -> None:
        df = _make_df([
            {"ts": "2024-01-01 09:00", "open": 18000, "high": 18100,
             "low": 17900, "close": 18050, "volume": 0},
            {"ts": "2024-01-01 09:01", "open": 18010, "high": 18110,
             "low": 17910, "close": 18060, "volume": 500},
        ])
        result = validate(df)
        assert len(result) == 1

    def test_converts_naive_ts_to_utc(self) -> None:
        df = pd.DataFrame({
            "ts": pd.to_datetime(["2024-01-01 09:00"]),
            "open": [18000], "high": [18100], "low": [17900],
            "close": [18050], "volume": [1000],
        })
        # naive datetime (no tz)
        assert df["ts"].dt.tz is None
        result = validate(df)
        assert str(result["ts"].dt.tz) == "UTC"

    def test_valid_dataframe_passes_through(self) -> None:
        df = _make_df([
            {"ts": "2024-01-01 09:00", "open": 18000, "high": 18100,
             "low": 17900, "close": 18050, "volume": 1000},
        ])
        result = validate(df)
        assert len(result) == 1

    def test_empty_dataframe_returns_empty(self) -> None:
        df = _make_df([])
        # add required columns to empty df
        for col in ["ts", "open", "high", "low", "close", "volume"]:
            df[col] = pd.Series([], dtype=float)
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        result = validate(df)
        assert result.empty


class TestFlagAnomalies:
    def test_no_warning_for_normal_moves(self, caplog: pytest.LogCaptureFixture) -> None:
        df = _make_df([
            {"ts": "2024-01-01 09:00", "open": 18000, "high": 18050,
             "low": 17980, "close": 18010, "volume": 1000},
            {"ts": "2024-01-01 09:01", "open": 18010, "high": 18060,
             "low": 17990, "close": 18020, "volume": 1000},
        ])
        with caplog.at_level("WARNING"):
            flag_anomalies(df, "NQ")
        assert "Anomaly" not in caplog.text

    def test_warning_for_large_move(self, caplog: pytest.LogCaptureFixture) -> None:
        df = _make_df([
            {"ts": "2024-01-01 09:00", "open": 18000, "high": 18050,
             "low": 17980, "close": 18000, "volume": 1000},
            {"ts": "2024-01-01 09:01", "open": 19100, "high": 19200,
             "low": 19000, "close": 19100, "volume": 1000},  # +6.1%
        ])
        with caplog.at_level("WARNING"):
            flag_anomalies(df, "NQ")
        assert "Anomaly" in caplog.text
        assert "NQ" in caplog.text

    def test_empty_df_does_not_raise(self) -> None:
        df = _make_df([])
        flag_anomalies(df, "NQ")  # should not raise
