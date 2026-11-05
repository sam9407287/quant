"""Daily-bar data layer tests (ADR-010 phase 1): no DB, no network."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd
import pytest

from app.pairs import schema
from app.pairs.data import (
    DAILY_COLUMNS,
    align_pair,
    fetch_daily_history,
    log_price_matrix,
    normalise_download,
    quality_check,
    upsert_daily_bars,
)

DATES = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"])


def _block(base: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [base, base + 1, base + 2],
            "High": [base + 2, base + 3, base + 4],
            "Low": [base - 1, base, base + 1],
            "Close": [base + 1, base + 2, base + 3],
            "Adj Close": [base + 0.5, base + 1.5, base + 2.5],
            "Volume": [100, 200, 300],
        },
        index=DATES,
    )


def _multi(tickers: list[str]) -> pd.DataFrame:
    return pd.concat({t: _block(100.0 * (i + 1)) for i, t in enumerate(tickers)}, axis=1)


class TestNormaliseDownload:
    def test_multi_ticker_frame_becomes_long(self) -> None:
        out = normalise_download(_multi(["ES=F", "NQ=F"]), ["ES=F", "NQ=F"])
        assert list(out.columns) == list(DAILY_COLUMNS)
        assert len(out) == 6
        assert set(out["ticker"]) == {"ES=F", "NQ=F"}
        assert out["trading_date"].iloc[0] == date(2026, 1, 5)
        es = out[out["ticker"] == "ES=F"]
        assert es["close"].tolist() == [101.0, 102.0, 103.0]
        assert es["adj_close"].tolist() == [100.5, 101.5, 102.5]

    def test_single_ticker_flat_columns(self) -> None:
        out = normalise_download(_block(50.0), ["KO"])
        assert out["ticker"].unique().tolist() == ["KO"]
        assert len(out) == 3

    def test_missing_ticker_in_batch_is_skipped(self) -> None:
        out = normalise_download(_multi(["ES=F"]), ["ES=F", "ZZ=F"])
        assert set(out["ticker"]) == {"ES=F"}

    def test_rows_without_close_are_dropped_and_adj_falls_back(self) -> None:
        block = _block(10.0)
        block.loc[DATES[1], "Close"] = np.nan
        block = block.drop(columns=["Adj Close"])
        out = normalise_download(block, ["X"])
        assert len(out) == 2
        assert (out["adj_close"] == out["close"]).all()

    def test_empty_download(self) -> None:
        out = normalise_download(pd.DataFrame(), ["ES=F"])
        assert out.empty and list(out.columns) == list(DAILY_COLUMNS)

    def test_flat_columns_with_many_tickers_is_an_error(self) -> None:
        with pytest.raises(ValueError):
            normalise_download(_block(1.0), ["A", "B"])


class TestFetchDailyHistory:
    def test_passes_inclusive_end_and_batch_flags(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_download(**kwargs: object) -> pd.DataFrame:
            calls.append(kwargs)
            return _multi(["ES=F", "NQ=F"])

        out = fetch_daily_history(["ES=F", "NQ=F"], date(2026, 1, 1), date(2026, 1, 7), downloader=fake_download)
        assert len(out) == 6
        kw = calls[0]
        assert kw["start"] == "2026-01-01"
        assert kw["end"] == "2026-01-08"  # exclusive upstream
        assert kw["interval"] == "1d" and kw["auto_adjust"] is False
        assert kw["group_by"] == "ticker"

    def test_no_tickers_short_circuits(self) -> None:
        out = fetch_daily_history([], date(2026, 1, 1), date(2026, 1, 7), downloader=lambda **k: _block(1.0))
        assert out.empty


def _long(rows: list[tuple[str, date, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": t, "trading_date": d, "open": c, "high": c, "low": c,
                "close": c, "adj_close": c, "volume": 1,
            }
            for t, d, c in rows
        ]
    )


class TestQualityCheck:
    def test_non_positive_and_future_rows_dropped(self) -> None:
        df = _long([
            ("A", date(2026, 1, 5), 100.0),
            ("A", date(2026, 1, 6), -1.0),
            ("A", date(2026, 1, 7), 101.0),
            ("A", date(2027, 1, 1), 102.0),
        ])
        clean, issues = quality_check(df, today=date(2026, 1, 8))
        assert len(clean) == 2
        kinds = sorted(i.kind for i in issues)
        assert kinds == ["future_date", "non_positive"]

    def test_duplicates_keep_first(self) -> None:
        df = _long([
            ("A", date(2026, 1, 5), 100.0),
            ("A", date(2026, 1, 5), 999.0),
        ])
        clean, issues = quality_check(df, today=date(2026, 1, 8))
        assert len(clean) == 1 and clean["close"].iloc[0] == 100.0
        assert issues[0].kind == "duplicate"

    def test_extreme_move_is_flagged_not_dropped(self) -> None:
        df = _long([
            ("A", date(2026, 1, 5), 100.0),
            ("A", date(2026, 1, 6), 140.0),  # +33.6% log move
            ("B", date(2026, 1, 5), 50.0),
            ("B", date(2026, 1, 6), 50.5),
        ])
        clean, issues = quality_check(df, today=date(2026, 1, 8))
        assert len(clean) == 4
        assert [i.kind for i in issues] == ["extreme_move"]
        assert issues[0].ticker == "A" and issues[0].trading_date == date(2026, 1, 6)

    def test_empty_frame(self) -> None:
        clean, issues = quality_check(pd.DataFrame(columns=DAILY_COLUMNS))
        assert clean.empty and issues == []


class TestUpsert:
    @pytest.mark.asyncio
    async def test_chunks_and_commits(self) -> None:
        rows = [("A", date(2026, 1, 1) if i == 0 else date.fromordinal(738000 + i), float(i + 1)) for i in range(4500)]
        df = _long(rows)
        df.loc[0, "volume"] = np.nan  # NaN volume must become NULL, not crash
        session = MagicMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        n = await upsert_daily_bars(session, df)
        assert n == 4500
        assert session.execute.await_count == 3  # 2000 + 2000 + 500
        first_batch = session.execute.await_args_list[0].args[1]
        assert first_batch[0]["volume"] is None
        assert isinstance(first_batch[1]["volume"], int)
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_frame_writes_nothing(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock()
        assert await upsert_daily_bars(session, pd.DataFrame(columns=DAILY_COLUMNS)) == 0
        session.execute.assert_not_awaited()


class TestAlignment:
    def _wide(self) -> pd.DataFrame:
        idx = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09"])
        return pd.DataFrame(
            {
                "Y": [10.0, 11.0, np.nan, 13.0, 14.0],
                "X": [20.0, np.nan, np.nan, 23.0, 24.0],
            },
            index=idx,
        )

    def test_one_day_fill_bridges_single_gap_only(self) -> None:
        pair = align_pair(self._wide(), "Y", "X", max_ffill=1)
        # 01-06: X filled from 01-05; 01-07: X gap is the 2nd consecutive → dropped.
        assert [d.strftime("%m-%d") for d in pair.index] == ["01-05", "01-06", "01-08", "01-09"]
        assert pair.loc["2026-01-06", "X"] == 20.0

    def test_no_fill_is_strict_inner_join(self) -> None:
        pair = align_pair(self._wide(), "Y", "X", max_ffill=0)
        assert len(pair) == 3

    def test_missing_column_returns_empty(self) -> None:
        assert align_pair(self._wide(), "Y", "Z").empty

    def test_log_matrix_drops_short_columns(self) -> None:
        wide = self._wide()
        logged = log_price_matrix(wide, max_ffill=1, min_rows=5)
        assert list(logged.columns) == ["Y"]
        assert logged["Y"].iloc[0] == pytest.approx(np.log(10.0))


class TestSchemaParity:
    def test_embedded_ddl_matches_migration_file(self) -> None:
        path = Path(__file__).resolve().parents[1] / "db" / "migrations" / "002_pairs.sql"
        file_stmts = schema.statements(path.read_text())
        embedded = schema.statements()
        assert [" ".join(s.split()) for s in file_stmts] == [" ".join(s.split()) for s in embedded]

    def test_statements_are_all_idempotent(self) -> None:
        for stmt in schema.statements():
            assert "IF NOT EXISTS" in stmt, stmt[:60]

    @pytest.mark.asyncio
    async def test_ensure_schema_runs_every_statement(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        n = await schema.ensure_schema(session)
        assert n == len(schema.statements()) == session.execute.await_count
        session.commit.assert_awaited_once()
