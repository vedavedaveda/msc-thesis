# Design

## Context

See proposal.md (Why) for the motivation. Current facts that shape the approach:

- **Pipeline.** Every step has its own CLI and a usage block in its module docstring:
  - `rejsekort.ingestion`: reads the encrypted archive at `ENCRYPTED_DIR` (`/mnt/raid/...`, using `~/.rkd_pass`) and writes `data/interim/rejsekort/rejsekort_<span>/`.
  - `rejsekort.cleaning`: writes `data/interim/rejsekort/clean_<span>/`.
  - `rejsekort.stop_timeseries`: writes `data/processed/stop_timeseries/<span>/`.
  - `data.build zero_shot`: writes `data/processed/zero_shot/...`.
  - `experiments.zero_shot.run`: writes `forecasts.parquet` and `metrics.json`.

  `<span>` is the year, a single day, or an inclusive day range (`ingestion.span_name`). The ingestion and cleaning spans must match.
- **Paths.** All paths come from `utils/paths.py`, and its docstring says never to hardcode them.
- **Data stays out of git.** `/data/` and `/outputs/` are gitignored, and the data is sensitive and lives on the server.
- **Environment.** Python 3.13 with `uv`. On Linux, torch comes from the `pytorch-cu126` index because the server's CUDA driver is 12.4; macOS uses the PyPI wheel. `run.py` sets `TORCH_DISABLE_NATIVE_JIT=1`.
- **Tests** use `tmp_path` and synthetic frames, so `uv run pytest` runs without the restricted data. This is the one thing an examiner can fully run.
- **Agents.** Agent tooling is already present: `.claude/`, `.github/` (Copilot prompts, skills, and a setup workflow that only installs the OpenSpec CLI) and `.agents/`. There is no `AGENTS.md` or `CLAUDE.md`.
- **The zero-shot change** has two spec folders, `forecast-metrics/` and `zero-shot-evaluation/`, that become durable specs when it's archived.
- **Uncommitted edits.** The working tree has uncommitted edits to `stop_timeseries.py` and `run.py`, and the docs must describe the code as it stands after those edits.

## Goals / Non-Goals

**Goals:**
- Each fact has exactly one home. Every other place links to it.
- Someone with server access can go from a fresh clone to `metrics.json` using only the README.
- Someone without data access can still install, run the tests, and understand the method.
- An agent gets enough context from `AGENTS.md` to follow the repo's conventions, without re-deriving them from code.

**Non-Goals:**
- No docs build tooling (mkdocs/Sphinx), no doc linting, no CI checks for docs.
- No rewriting of module docstrings or YAML comments. They stay the source of truth for per-step detail.
- No documentation of the ABM utils' internals. They are labelled as planned, not explained.

## Decisions

**1. Layered docs with a single source of truth per fact.**

```
README.md            orientation: what, setup, data access, pipeline, map
  |-- docs/data/rejsekort.md        domain semantics of the source data
  |-- docs/experiments/<name>.md    one page per experiment
  |-- configs/*.yaml (comments)     per-parameter meaning   <- authoritative
  `-- module docstrings             per-step CLI usage      <- authoritative
AGENTS.md            conventions + commands for agents, links to the above
openspec/specs/      requirements (what the system promises)
```

The docs summarize and link. They never copy parameter tables or CLI flags, which already live in configs and `--help`. *Alternative considered:* a single large README. Rejected because it mixes onboarding with method detail, and every new experiment would make it longer.

**2. `AGENTS.md` is canonical, `CLAUDE.md` contains only `@AGENTS.md`.** Copilot and Codex read `AGENTS.md`, and Claude Code follows the `@` import, so the content is maintained in one place. *Alternatives considered:* a full `CLAUDE.md` plus `.github/copilot-instructions.md`, rejected because the two would drift; a symlink, rejected because it breaks on some checkouts and tools.

**3. `AGENTS.md` holds conventions, not narrative.** It is a short list of rules and commands:
- how to run tests
- the per-step CLI pattern and `--set` overrides
- one config per step
- import paths from `utils/paths.py`
- the builder registry recipe
- output layout
- never write under `data/raw` or to the server archive
- the OpenSpec workflow: propose, then apply, then archive

Explanations go in README and `docs/`, and `AGENTS.md` links to them. Keeping it short keeps per-session token cost low and makes the rules easy for agents to follow.

**4. The zero-shot section moves to `docs/experiments/zero_shot.md` without changes, then gets small additions.** Its text is already accurate, so it moves first and is extended second (the outputs layout and how to re-score). This keeps the diff easy to review. README keeps a two-line pointer.

**5. The Rejsekort page is new, but its facts come from the code and configs.** The sources are:
- `configs/stop_timeseries.yaml`: the Model codes and the transactions-vs-passengers note
- the `cleaning.py` docstring: deduplication and per-day processing
- `ingestion.py`: the region filter on `TakstOmraade`, the encoding, and the archive name pattern

The page explains the *why* and links to the YAML for the actual values. It contains no new claims about the data.

**6. The repo map uses three status labels:** `active`, `planned`, and `planned / unverified (imported, not integrated)`. Labels are per module or per package, not per function. *Alternative considered:* leaving the stubs out of the map. Rejected because readers would still find them and wonder what they are.

**7. Examiner reproducibility is described in tiers in README:**
- (a) install and run the tests: anyone
- (b) rebuild from raw data: needs server access and `~/.rkd_pass`
- (c) re-score existing forecasts: needs `forecasts.parquet`

This states clearly what can be reproduced and by whom, without promising more.

**8. OpenSpec housekeeping.**
- Archive `zero-shot-chronos-eval` with `openspec archive`, which syncs its two specs into `openspec/specs/`.
- Fill the `context` field in `openspec/config.yaml` with a few lines of constraints that can't be inferred from code:
  - parity with the mobility-baselines Chronos-2 reference
  - the data is restricted and server-only
  - docs are written for authors, agents, and later an examiner
  - Python 3.13 / uv

  It does not describe the codebase, because the config's own guidance says to keep discoverable facts out.

## Risks / Trade-offs

- [Docs drift from code as experiments evolve] → Docs link to docstrings and configs instead of copying them. `AGENTS.md` tells agents to update README, `docs/` and `AGENTS.md` when they change a CLI, config key, or output path.
- [Uncommitted edits change behavior the docs describe] → Write the docs against the working tree, and commit those edits before or together with the docs.
- [Server paths in public docs] → `/mnt/raid/...` and `~/.rkd_pass` are already in the code, so naming them adds no exposure. The docs must never include passwords, archive contents, or sample rows of real data.
- ["Planned" labels hide dead code] → Accepted for now (user decision). The labels make the state visible, and a later change can delete or integrate the code.
- [Archiving fails validation] → Run `openspec validate zero-shot-chronos-eval` first and fix any spec format issues before archiving.
