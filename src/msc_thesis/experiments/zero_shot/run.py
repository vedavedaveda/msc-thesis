"""Zero-shot Chronos-2 evaluation, following mobility-baselines Chronos-2-evaluation (main.py, utils.evaluation_loop).

    uv run python -m msc_thesis.experiments.zero_shot.run
    uv run python -m msc_thesis.experiments.zero_shot.run --set n_test_days=1 --set start_test_day=90

Reads data/processed/zero_shot/<year>/series.parquet (built by `python -m msc_thesis.data.build
zero_shot`) and, for every forecast time in the test period, feeds Chronos-2 the previous 7 days of
the target and past covariates for all stops (cross-learning on). Forecast rows for each configured
horizon are written to forecasts.parquet and scored into metrics.json beside it.

Reference behaviour kept on purpose (see metrics.py for the metric side):
  * each forecast predicts `prediction_length + 1` bins;
  * horizon `h` minutes is scored at forecast time + h, so the first predicted bin is never scored;
  * forecast times run from the test start up to (test end - largest horizon), one per stride.
"""

import os

# torch 2.14 JIT-compiles some CUDA ops with Triton, which needs a C compiler that the server
# lacks. This switch makes torch use its regular kernels instead; it must be set before torch loads.
os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")

import argparse  # noqa: E402
import datetime as dt  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, Protocol  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import polars as pl  # noqa: E402
import yaml  # noqa: E402

from msc_thesis.data.builders.base import Config, load_config  # noqa: E402
from msc_thesis.data.builders.zero_shot import EXPERIMENT, window  # noqa: E402
from msc_thesis.experiments.zero_shot.metrics import score_forecasts  # noqa: E402
from msc_thesis.utils.fs import atomic_file  # noqa: E402
from msc_thesis.utils.logging import get_logger  # noqa: E402
from msc_thesis.utils.paths import PROCESSED_DIR  # noqa: E402

log = get_logger(__name__)

HISTORY_MINUTES = 7 * 24 * 60   # one week of context, as in the reference
LOWER_Q, UPPER_Q = 0.1, 0.9     # interval used for coverage and width (reference: probabilistic_metrics)
ID_COLUMN, TIMESTAMP_COLUMN = "item_id", "timestamp"


class Pipeline(Protocol):
    def predict_df(self, df: pd.DataFrame, **kwargs: Any) -> pd.DataFrame: ...


def series_path(year: int) -> Path:
    return PROCESSED_DIR / EXPERIMENT / str(year) / "series.parquet"


def validate_config(cfg: Config) -> None:
    freq, pred_len = cfg["freq"], cfg["prediction_length"]
    bad = [h for h in cfg["horizons"] if h % freq or not 0 < h <= pred_len * freq]
    if bad:
        raise ValueError(
            f"horizons must be positive multiples of freq={freq} and at most "
            f"prediction_length * freq = {pred_len * freq} minutes, got {bad}"
        )
    for q in (LOWER_Q, UPPER_Q):
        if not any(abs(q - level) < 1e-8 for level in cfg["quantile_levels"]):
            raise ValueError(f"quantile_levels must include {q}, got {cfg['quantile_levels']}")


def forecast_times(cfg: Config) -> list[pd.Timestamp]:
    """Forecast times: test start, then every stride, while the largest horizon stays inside the test period."""
    _, test_start, end = window(cfg)
    freq, stride = cfg["freq"], cfg["stride_steps"]
    # the last scored bin starts at t + max horizon and must start before end - freq
    last = end - test_start - dt.timedelta(minutes=freq + max(cfg["horizons"]))
    n = last // dt.timedelta(minutes=stride * freq) + 1
    return [pd.Timestamp(test_start) + pd.Timedelta(minutes=k * stride * freq) for k in range(n)]


def context_slice(df: pd.DataFrame, t: pd.Timestamp, columns: list[str]) -> pd.DataFrame:
    """Rows in [t - 7 days, t): target and past covariates only, nothing at or after t."""
    start = t - pd.Timedelta(minutes=HISTORY_MINUTES)
    ts = df[TIMESTAMP_COLUMN]
    return df.loc[(ts >= start) & (ts < t), columns].copy()


def _quantile_column(forecast: pd.DataFrame, q: float) -> str:
    for c in forecast.columns:
        try:
            if abs(float(c) - q) < 1e-8:
                return c
        except (TypeError, ValueError):
            continue
    raise ValueError(f"Quantile {q} not found in forecast columns {list(forecast.columns)}")


def window_rows(forecast: pd.DataFrame, df: pd.DataFrame, t: pd.Timestamp, cfg: Config) -> pl.DataFrame:
    """Scored rows of one forecast: one block per horizon, joined with the truth at t + h."""
    target = cfg["target"]
    if "target_name" in forecast.columns:
        forecast = forecast[forecast["target_name"] == target]
    low_col, high_col = _quantile_column(forecast, LOWER_Q), _quantile_column(forecast, UPPER_Q)
    blocks = []
    for h in cfg["horizons"]:
        ts = t + pd.Timedelta(minutes=h)
        truth = df.loc[df[TIMESTAMP_COLUMN] == ts, [ID_COLUMN, target]]
        merged = truth.merge(
            forecast.loc[forecast[TIMESTAMP_COLUMN] == ts, [ID_COLUMN, "predictions", low_col, high_col]],
            on=ID_COLUMN,
            how="inner",
        )
        if merged.empty:
            raise ValueError(f"No data to evaluate for horizon {h} min at forecast time {t}")
        blocks.append(pl.DataFrame({
            "item_id": merged[ID_COLUMN].astype(str).to_list(),
            "forecast_time": t.to_pydatetime(),
            "timestamp": ts.to_pydatetime(),
            "horizon": h,
            "prediction": merged["predictions"].astype(float).to_numpy(),
            "q_low": merged[low_col].astype(float).to_numpy(),
            "q_high": merged[high_col].astype(float).to_numpy(),
            "truth": merged[target].astype(float).to_numpy(),
        }))
    return pl.concat(blocks)


def run_windows(pipeline: Pipeline, df: pd.DataFrame, cfg: Config) -> pl.DataFrame:
    """Sliding-window forecast loop; returns the scored rows of every window and horizon."""
    validate_config(cfg)
    target = cfg["target"]
    columns = [ID_COLUMN, TIMESTAMP_COLUMN, target, *cfg["past_covariates"]]
    times = forecast_times(cfg)
    log.info("Forecasting %d windows, horizons %s min", len(times), cfg["horizons"])
    out = []
    for i, t in enumerate(times, 1):
        forecast = pipeline.predict_df(
            context_slice(df, t, columns),
            future_df=None,
            prediction_length=cfg["prediction_length"] + 1,
            quantile_levels=cfg["quantile_levels"],
            id_column=ID_COLUMN,
            timestamp_column=TIMESTAMP_COLUMN,
            target=target,
            cross_learning=cfg["cross_learning"],
        )
        out.append(window_rows(forecast, df, t, cfg))
        if i % 50 == 0 or i == len(times):
            log.info("window %d/%d (%s)", i, len(times), t)
    return pl.concat(out)


def set_seed(seed: int) -> None:
    import torch

    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    np.random.seed(seed)


def load_series(cfg: Config) -> pd.DataFrame:
    path = series_path(cfg["year"])
    if not path.exists():
        raise FileNotFoundError(
            f"Series not found: {path}. Run `python -m msc_thesis.data.build zero_shot` first."
        )
    df = pl.read_parquet(path).to_pandas()
    steps = df[TIMESTAMP_COLUMN].drop_duplicates().sort_values().diff().dropna().unique()
    if len(steps) != 1 or pd.Timedelta(steps[0]) != pd.Timedelta(minutes=cfg["freq"]):
        raise ValueError(f"Series bins do not match freq={cfg['freq']} min; found steps {list(steps)}")
    _, test_start, end = window(cfg)
    need_start = pd.Timestamp(test_start) - pd.Timedelta(minutes=HISTORY_MINUTES)
    need_end = pd.Timestamp(end) - pd.Timedelta(minutes=cfg["freq"])
    have_start, have_end = df[TIMESTAMP_COLUMN].min(), df[TIMESTAMP_COLUMN].max()
    if have_start > need_start or have_end < need_end:
        raise ValueError(
            f"{path} covers {have_start} to {have_end}, but this config needs {need_start} to {need_end} "
            "(one week of context before the test start, through the last test bin). Rebuild it with "
            "`python -m msc_thesis.data.build zero_shot` using the same start_date and split settings."
        )
    return df


def load_pipeline(model_id: str) -> Pipeline:
    import torch
    from chronos import BaseChronosPipeline

    return BaseChronosPipeline.from_pretrained(model_id, device_map="cuda" if torch.cuda.is_available() else "cpu")


def write_outputs(forecasts: pl.DataFrame, cfg: Config) -> Path:
    out_dir = PROCESSED_DIR / EXPERIMENT / str(cfg["year"])
    out_dir.mkdir(parents=True, exist_ok=True)
    # Score before touching the outputs, so a failed run leaves the previous pair intact.
    summary = json.dumps({"config": cfg, **score_forecasts(forecasts)}, indent=2, default=str)
    with atomic_file(out_dir / "forecasts.parquet") as fc_tmp, atomic_file(out_dir / "metrics.json") as m_tmp:
        forecasts.write_parquet(fc_tmp, compression="zstd")
        m_tmp.write_text(summary)
    return out_dir


def run(cfg: Config, pipeline: Pipeline | None = None) -> Path:
    df = load_series(cfg)
    set_seed(cfg["seed"])
    pipeline = pipeline or load_pipeline(cfg["model_id"])
    out_dir = write_outputs(run_windows(pipeline, df, cfg), cfg)
    log.info("Wrote forecasts and metrics to %s", out_dir)
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", dest="overrides", action="append", default=[], metavar="KEY=VALUE")
    args = parser.parse_args()

    cfg = load_config("zero_shot")
    for item in args.overrides:
        key, sep, value = item.partition("=")
        if not sep or key not in cfg:
            parser.error(f"--set expects KEY=VALUE with a key from the config ({sorted(cfg)}), got {item!r}")
        cfg[key] = yaml.safe_load(value)

    out_dir = run(cfg)
    metrics = json.loads((out_dir / "metrics.json").read_text())
    print(json.dumps(metrics["overall"], indent=2))


if __name__ == "__main__":
    main()
