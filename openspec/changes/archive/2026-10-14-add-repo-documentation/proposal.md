# Proposal

## Why

Code-level docs are decent: most modules have a docstring and the configs carry comments. What's missing is documentation that ties the repo together. There is no pipeline map, no setup or data-access guide, and no context file for agents, and important domain facts (Rejsekort event codes, the transactions-vs-passengers finding) live only in YAML comments. The readers are the two thesis authors, coding agents (Claude, Copilot, Codex) and, later, an examiner who may run the code. All of them currently have to reconstruct the chain ingestion -> cleaning -> stop_timeseries -> build -> run from source, and that gets harder as more experiments are added.

## What Changes

- **README.md becomes the human hub and the examiner's entry point**:
  - what the repo is and its current status
  - setup with `uv sync`, including the Linux CUDA 12.6 vs macOS torch wheels
  - data access: the Rejsekort data is restricted, where it lives, and what can and cannot be reproduced without it
  - an end-to-end pipeline diagram with the command for each step
  - a repo map with one line per package
  - links into `docs/`
- **The zero-shot section moves out of README** into `docs/experiments/zero_shot.md` (paper-parity notes, outputs, re-scoring). README keeps a short pointer.
- **New `docs/data/rejsekort.md`** covers:
  - the `Model` event codes and how they map to check-in and check-out
  - why `count_mode: transactions` is used
  - the cleaning rules
  - the ingestion/cleaning span coupling

  It links to the YAML comments in `configs/` instead of copying them, so the two cannot drift apart.
- **New `AGENTS.md`** gives agents terse working context:
  - commands and how to run tests
  - `--set KEY=VALUE` overrides
  - one config per pipeline step
  - how to add a builder (module + `configs/<name>.yaml` + `REGISTRY`)
  - output layout under `data/processed/<step>/<year>/`
  - never write to raw data
  - the OpenSpec workflow

  **New `CLAUDE.md`** contains only `@AGENTS.md`.
- **The repo map marks unfinished parts honestly:**
  - `utils/run_calibration.py` and `utils/simulation_utils.py` (and, found during apply, `utils/config.py` and `utils/load.py`, which share their origin) are marked "planned / unverified (imported, not integrated)". They come from a disruption-ABM codebase, nothing references them, and `pyraptor` is not a dependency.
  - The empty stub modules are marked "planned": `data/events/*`, `data/integration/*`, `rejsekort/od_flows.py`, `rejsekort/passenger_counts.py`.

  None of these files are modified.
- **Archive `zero-shot-chronos-eval`** (all 11 tasks are complete) so its requirements become the first durable spec under `openspec/specs/`.
- **Fill the `context` field in `openspec/config.yaml`** with constraints that can't be inferred from code: parity with the mobility-baselines reference setup, restricted data, and the readers named above.

Out of scope:
- a docstring pass over public functions
- deleting or integrating the ABM utils and stubs
- generated API docs (Sphinx/mkdocs)

## Capabilities

### New Capabilities
None. This is a documentation and tooling change with no spec-level behavior. The change should set `skip_specs: true` in `.openspec.yaml`. The durable spec added by archiving `zero-shot-chronos-eval` belongs to that change, not this one.

### Modified Capabilities
None.

## Impact

- New files: `AGENTS.md`, `CLAUDE.md`, `docs/data/rejsekort.md`, `docs/experiments/zero_shot.md`.
- Modified: `README.md`, `openspec/config.yaml`.
- OpenSpec: `openspec/changes/zero-shot-chronos-eval` moves to the archive, and `openspec/specs/` gains its spec(s).
- No changes to code, configs (other than `openspec/config.yaml`) or dependencies.
- Agent setup: `AGENTS.md` is picked up by Copilot and Codex. The existing `.github/agents/openspec.agent.md` is unchanged.
