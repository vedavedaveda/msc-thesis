# Tasks

## 1. OpenSpec housekeeping

- [x] 1.1 Archive `zero-shot-chronos-eval` with `openspec archive zero-shot-chronos-eval`. Verify that `openspec list --specs` shows `forecast-metrics` and `zero-shot-evaluation`, and that the change no longer appears in `openspec list`.
- [x] 1.2 Fill the `context` field in `openspec/config.yaml` with the non-inferable constraints from design.md, Decision 8: mobility-baselines parity, restricted server-only data, the doc readers, and Python 3.13/uv. Keep it under about 10 lines. Verify that `openspec context --json` still resolves the root and that the YAML parses.

## 2. Domain and experiment docs

- [x] 2.1 Move the zero-shot section from `README.md` to `docs/experiments/zero_shot.md` unchanged. Verify with a diff that the moved text matches the original word for word.
- [x] 2.2 Extend `docs/experiments/zero_shot.md` with:
  - the full prerequisite chain (stop_timeseries for `year` must exist)
  - the outputs layout under `data/processed/zero_shot/<year>/`
  - how to re-score with `metrics.score_forecasts`
  - links to `configs/zero_shot.yaml` and the `zero-shot-evaluation` / `forecast-metrics` specs

  Verify that every command and path on the page appears in a `run.py`/`build.py`/`zero_shot.py` docstring, error message or `paths.py`.
- [x] 2.3 Write `docs/data/rejsekort.md` covering:
  - the source archive and region filter (`TakstOmraade`)
  - how spans are named (year, day or range) and why the ingestion and cleaning spans must match
  - the cleaning rules (dedup, per-day processing)
  - the Model codes with their in/out/ignore mapping
  - the transactions-vs-passengers finding

  The page links to `configs/stop_timeseries.yaml` for the actual values. Verify that each fact traces to `ingestion.py`, `cleaning.py`, `stop_timeseries.py` or the YAML comments, with no new claims, and that the page includes no real data rows or credentials.

## 3. README hub

- [x] 3.1 Rewrite `README.md`:
  - purpose and status
  - setup (`uv sync`; Linux cu126 vs macOS torch; `TORCH_DISABLE_NATIVE_JIT`)
  - data access (server archive and `~/.rkd_pass`, with nothing secret)
  - an ASCII pipeline diagram with one command per step and its output path
  - the reproducibility tiers from design.md, Decision 7
  - links to `docs/` and `AGENTS.md`
  - a two-line pointer to the zero-shot page

  Verify that every command in the README matches the usage block in the corresponding module docstring.
- [x] 3.2 Add a repo map to `README.md` with one line per package/module and its status:
  - `active` for the live pipeline modules
  - `planned` for `data/events/*`, `data/integration/*`, `rejsekort/od_flows.py`, `rejsekort/passenger_counts.py`
  - `planned / unverified (imported, not integrated)` for `utils/run_calibration.py`, `utils/simulation_utils.py`
  - `scrap/` described as exploratory notebooks

  Verify that every entry under `src/msc_thesis/` appears exactly once.

## 4. Agent context

- [x] 4.1 Write `AGENTS.md` as a list of conventions and commands (design.md, Decision 3):
  - `uv run pytest`
  - the per-step CLI pattern and `--set KEY=VALUE`
  - one config per step in `configs/`
  - paths only from `utils/paths.py`
  - the builder recipe (module + yaml + `REGISTRY`)
  - output layout
  - never write to raw data or the server archive
  - the OpenSpec flow (explore/propose/apply/archive)
  - keep README/`docs/`/`AGENTS.md` in sync when a CLI, config key or output path changes
  - links to README and `docs/`

  Verify that it is under about 80 lines and that every rule matches the code.
- [x] 4.2 Create `CLAUDE.md` containing only `@AGENTS.md`. Verify that a fresh Claude Code session in the repo loads the `AGENTS.md` content (`/memory` lists it).

## 5. Integration check

- [x] 5.1 Run `uv run pytest` and confirm it passes, since the docs say this works without data. Check every relative link in `README.md`, `AGENTS.md` and `docs/**` with `grep -o '](\S*)'`, confirming each target exists. Run `openspec validate add-repo-documentation` and confirm it passes.
