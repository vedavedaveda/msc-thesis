# msc-thesis

Code for our MSc thesis. It turns Rejsekort travel-card taps into check-in/check-out time series
per stop and evaluates forecasting models on them.

**Status:** the Rejsekort pipeline (ingestion → cleaning → stop time series) and a first
experiment, zero-shot Chronos-2 forecasting, are working. Event data and its integration with
stations are planned (see the [repo map](#repo-map)).

Agents: start with [AGENTS.md](AGENTS.md).

## Setup

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                 # installs the package, dependencies and dev tools
uv run pytest           # runs without any restricted data
```

`torch` comes from a different source per platform (see `[tool.uv.sources]` in `pyproject.toml`).
On Linux it is the `pytorch-cu126` index, because the server's CUDA 12.4 driver cannot run the
default wheel and torch would silently fall back to CPU. On macOS it is the regular PyPI wheel.
`experiments/zero_shot/run.py` sets `TORCH_DISABLE_NATIVE_JIT=1` (unless already set), because
torch's Triton-compiled ops need a C compiler the server lacks.

## Data access

The Rejsekort data is restricted and lives only on the server. Ingestion reads the encrypted yearly
archives from `/mnt/raid/data_sortedmob/RKD/RawFiles/encrypted` (`ENCRYPTED_DIR` in
`src/msc_thesis/utils/paths.py`) and decrypts them with a password stored in `~/.rkd_pass`. Get both
from the data owner. All outputs go under `data/`, which is gitignored. Never commit data or
credentials.

## Pipeline

Each step is a module with its own CLI; its docstring has the full usage. Steps that read a config
use `configs/<step>.yaml` and accept `--set KEY=VALUE` overrides.

```
encrypted archive (server)
  │  uv run python -m msc_thesis.data.rejsekort.ingestion --year 2017
  ▼  data/interim/rejsekort/rejsekort_<span>/          raw rows, Copenhagen fare area
  │  uv run python -m msc_thesis.data.rejsekort.cleaning --year 2017
  ▼  data/interim/rejsekort/clean_<span>/              deduplicated, typed
  │  uv run python -m msc_thesis.data.rejsekort.stop_timeseries --year 2017
  ▼  data/processed/stop_timeseries/<span>/            check-ins/outs per stop and bin
  │  uv run python -m msc_thesis.data.build zero_shot
  ▼  data/processed/zero_shot/<year>/series.parquet    Chronos input
  │  uv run python -m msc_thesis.experiments.zero_shot.run
  ▼  data/processed/zero_shot/<year>/forecasts.parquet, metrics.json
```

`<span>` is the year, or a day or day range when you pass `--day` / `--start --end`. Ingestion and
cleaning must use the same span. On a first run, `stop_timeseries` stops and prints the per-code
event counts until `check_type_map_confirmed` is true in `configs/stop_timeseries.yaml`. See
[docs/data/rejsekort.md](docs/data/rejsekort.md) for why.

**Step-by-step run instructions** (spans, day-range zero-shot runs, troubleshooting):
[docs/running.md](docs/running.md).

## Experiments

- **Zero-shot Chronos-2**, mirroring the mobility-baselines Citi Bike setup.
  Details, outputs and re-scoring: [docs/experiments/zero_shot.md](docs/experiments/zero_shot.md).

## Reproducing results

| What | Who can do it | How |
|---|---|---|
| Install and run the tests | anyone | `uv sync && uv run pytest` |
| Rebuild everything from raw data | server access and `~/.rkd_pass` | [docs/running.md](docs/running.md) |
| Re-score existing forecasts | anyone with `forecasts.parquet` | [re-scoring](docs/experiments/zero_shot.md#re-scoring) |

## Repo map

```
src/msc_thesis/
  data/
    build.py                      active    CLI: build one experiment's dataset (builder registry)
    builders/
      base.py                     active    builder contract: config in, output folder out
      zero_shot.py                active    stop time series -> Chronos series.parquet
    rejsekort/
      ingestion.py                active    encrypted archive -> interim parquet
      cleaning.py                 active    dedupe, parse, drop unusable rows
      stop_timeseries.py          active    check-ins/outs per stop and time bin
      od_flows.py                 planned   empty
      passenger_counts.py         planned   empty
    events/                       planned   empty: ingestion.py, cleaning.py, build_calendar.py
    integration/                  planned   empty: event_station_matching.py
  experiments/
    zero_shot/
      run.py                      active    sliding-window Chronos-2 forecast + scoring
      metrics.py                  active    reference-parity metrics, re-scoring
  utils/
    paths.py                      active    every filesystem location
    yaml_config.py                active    load configs/<name>.yaml, --set overrides
    fs.py                         active    atomic file and folder writes
    logging.py                    active    logger setup
    config.py                     planned / unverified (imported, not integrated)
    load.py                       planned / unverified (imported, not integrated)
    run_calibration.py            planned / unverified (imported, not integrated)
    simulation_utils.py           planned / unverified (imported, not integrated)
configs/                          one YAML per configurable step (events.yaml, rejsekort.yaml: empty)
tests/                            pytest on synthetic data (test_events.py, test_integration.py: empty)
docs/                             run instructions, data and experiment pages
openspec/                         specs and change proposals (OpenSpec)
scrap/                            exploratory notebooks, not part of the pipeline
main.py                           uv project placeholder
```

The four `planned / unverified` utils come from an earlier disruption agent-based-model codebase.
Nothing imports them, and their dependencies (e.g. `pyraptor`) are not installed.
