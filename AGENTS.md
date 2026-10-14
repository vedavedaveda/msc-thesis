# AGENTS.md

Working rules for coding agents in this repo. For explanations, see [README.md](README.md) (setup,
pipeline, repo map), [docs/data/rejsekort.md](docs/data/rejsekort.md) (data semantics) and
[docs/experiments/](docs/experiments/) (one page per experiment).

## Commands

- Install: `uv sync`. Python 3.13; use `uv run ...`, never a bare `pip install`.
- Test: `uv run pytest`. Tests use `tmp_path` and synthetic frames, never the real data. Keep it
  that way for new tests.
- Run a step: `uv run python -m msc_thesis.<module> ...`. Each CLI module's docstring holds its usage.

## Configs and CLIs

- One YAML per configurable step in `configs/<name>.yaml`, loaded with
  `msc_thesis.utils.yaml_config.load_config(name)`. Comment every key in the YAML; that comment is
  the documentation for the key.
- CLIs that take a config accept repeatable `--set KEY=VALUE` (VALUE parsed as YAML; unknown keys
  are a usage error). Use `add_override_arg` / `apply_overrides` for new CLIs.
- Rejsekort ingestion and cleaning take only `--year` and `--day` / `--start --end`. Cleaning must
  use the same span as the ingestion it reads.

## Paths and outputs

- Import every location from `msc_thesis/utils/paths.py`. Never hardcode a data path.
- Layout: `data/interim/rejsekort/{rejsekort,clean}_<span>/`, then
  `data/processed/<step or experiment>/<year or span>/`.
- Write outputs atomically with `utils/fs.py` (`atomic_file`, `tmp_dir_for` + `publish_dir`), so
  a failed run never leaves a partial output.
- Never write under `data/raw/` or to the server archive (`ENCRYPTED_DIR`). Never commit anything
  under `data/` or `outputs/`, credentials, or real data rows (also not in notebooks or docs).

## Adding an experiment dataset (builder)

1. Write `build_<name>(cfg) -> Path` in `msc_thesis/data/builders/<name>.py`. It reads the
   canonical interim/processed tables and writes to `data/processed/<name>/`.
2. Add `configs/<name>.yaml`.
3. Register it in `REGISTRY` in `msc_thesis/data/builders/__init__.py`. It is then available as
   `uv run python -m msc_thesis.data.build <name>`.
4. Put the experiment's run/eval code in `msc_thesis/experiments/<name>/` and document it in
   `docs/experiments/<name>.md`.

## Domain rules

- Zero-shot code deliberately mirrors the mobility-baselines Chronos-2 reference, quirks included
  (see `docs/experiments/zero_shot.md`). Do not "fix" those quirks without an OpenSpec change.
- Rejsekort `Model` codes map to in/out/ignore only via `check_type_map` in
  `configs/stop_timeseries.yaml`. Unmapped codes must keep raising, not be dropped.
- `utils/config.py`, `utils/load.py`, `utils/run_calibration.py` and `utils/simulation_utils.py`
  are imported from another project and not integrated. Do not import or extend them.
  The empty stub modules are placeholders.

## Workflow

- Non-trivial changes go through OpenSpec: explore → propose → apply → archive
  (`/opsx:explore`, `/opsx:propose`, `/opsx:apply`, `/opsx:archive`). Durable requirements live in
  `openspec/specs/`, and active changes in `openspec/changes/`.
- When you change a CLI, a config key or an output path, update README.md, the matching page in
  `docs/` and this file in the same change.
