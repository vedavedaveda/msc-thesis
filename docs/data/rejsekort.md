# Rejsekort data

Rejsekort is the Danish travel-card system. Each row of the source data is one card tap (an *event*).
This page explains what the pipeline assumes about that data and why. Exact values live in
[`configs/stop_timeseries.yaml`](../../configs/stop_timeseries.yaml) and the module docstrings;
where this page and those disagree, they win.

The data is restricted. It exists only on the server and never enters git (`/data/` is gitignored).
Do not paste rows, card numbers or archive contents into docs, issues or notebooks you commit.

## Source archive and region filter

`data/rejsekort/ingestion.py` reads one encrypted archive per year,
`DTU_SJAELLAND_<year>.tar.gz.aes-256-cbc`, from `ENCRYPTED_DIR` in `utils/paths.py`. It decrypts
with the password in `~/.rkd_pass` and streams the CSV (ISO-8859-1) in chunks, so nothing decrypted
is written to disk and the full year is never in memory.

From each chunk it keeps:

- a fixed subset of columns (`SCHEMA` in `ingestion.py`);
- only rows whose `TakstOmraade` (fare area) is `Hovedstadsområdet`.

The result is a parquet dataset under `data/interim/rejsekort/rejsekort_<span>/`, partitioned by
journey date (`RejseDato`, one folder per day).

## Spans

Every Rejsekort step takes `--year`, plus optionally `--day` or `--start/--end` (inclusive) for a
smaller test run. The span becomes part of the folder name (`ingestion.span_name`):

| Flags | `<span>` |
|---|---|
| `--year 2019` | `2019` |
| `--year 2019 --day 2019-03-05` | `2019-03-05` |
| `--year 2019 --start 2019-03-04 --end 2019-03-11` | `2019-03-04_2019-03-11` |

Cleaning reads `rejsekort_<span>` and writes `clean_<span>`, so **cleaning must be run with the same
span flags as the ingestion it cleans**; otherwise it fails with "Ingested dataset not found... Run
ingestion first." `stop_timeseries` with span flags likewise reads `clean_<span>` and writes
`data/processed/stop_timeseries/<span>/`, leaving the full-year output alone.

A day range still decrypts the whole archive, because it is a single compressed stream. It only
makes the output smaller.

## Cleaning rules

`data/rejsekort/cleaning.py` is experiment-agnostic and works one `RejseDato` partition at a time:

1. **Deduplicate** on the untouched raw row (all columns). Identical rows always share a
   `RejseDato`, so per-day deduplication removes every duplicate. Two columns are ingested only so
   that duplicates are judged on the full row, and are dropped after this step.
2. **Parse** `Msgreportdate` into `event_time`. It is the only time column and is treated as the
   tap time: local time, no timezone. The repeated autumn DST hour cannot be told apart.
3. **Drop** rows whose time does not parse, whose year differs from `--year`, or that have no
   `StopPointNr`.

## Event codes (`Model`)

The `Model` column says what kind of tap a row is. `stop_timeseries.py` maps each code to a
check-in, a check-out or *ignore* via `check_type_map` in the YAML. The code meanings come from the
data owner and are documented in the YAML comments. The current mapping is:

| Code | Meaning | Counted as |
|---|---|---|
| `Fi` | first check-in | in |
| `Su` | transfer check-in | in |
| `Tr` | check-in after a check-out (`Co` + `Tr` = `Su`) | in |
| `Co` | check-out | out |
| `Cc` | cancellation via check-out (no charge) | out, so it balances its `Fi` |
| `Io` | unknown | ignore (in neither channel) |

No intermediate check-out is inferred for `Su` transfers.

The step is strict on purpose:

- a code missing from `check_type_map` raises instead of being dropped;
- it refuses to run until `check_type_map_confirmed: true`, and prints the per-code event counts so
  the map can be reviewed first. The YAML currently has `false`, pending a decision on `Io`.

## Transactions, not passengers

`count_mode` chooses how events are weighted:

- `transactions`: one per event row;
- `passengers`: the sum of `PassagerAntal1..3` over the person types in `person_type_codes`.

Passenger counts turn out to be recorded only on check-out rows. A check on 2017-06-19..26 found
about 0.99 passengers per `Co` event, while `Fi` rows summed to about 1.7% of their event count.
`passengers` would therefore give near-zero check-ins. Since a tap is about one person,
**`count_mode: transactions` is used**. The details are in the YAML comment next to `count_mode`.

## Stop time series

`stop_timeseries.py` bins the counted events into `check_ins` and `check_outs` per stop
(`StopPointNr`, kept as `stop_id`; stops are not merged into stations) and per `interval_minutes`
bin. Bins are left-closed and labelled by their start. With `dense_output: true`, every
(bin, stop) pair is written, and a zero means "no recorded events", not proof that the feed was
complete. The module docstring lists the output columns and the remaining assumptions.
