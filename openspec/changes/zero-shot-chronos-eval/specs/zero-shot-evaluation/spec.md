# Spec Delta

## Purpose

Run a pretrained Chronos-2 model zero-shot over the Rejsekort stop series in a sliding-window evaluation that follows the mobility-baselines Chronos-2 Citi Bike setup, and persist forecasts for later scoring.

## ADDED Requirements

### Requirement: Evaluation input
The system SHALL read the long table written by the zero-shot builder for the configured year and use the configured target and past covariates, with no future covariates.

#### Scenario: Series present
- **WHEN** `data/processed/zero_shot/<year>/series.parquet` exists
- **THEN** the run uses its `item_id`, `timestamp`, target and past covariate columns

#### Scenario: Series missing
- **WHEN** the series file does not exist
- **THEN** the run fails with an error naming the file and the builder command to create it

### Requirement: Sliding forecast windows
The system SHALL forecast from every bin boundary in the test period, stepping by `stride_steps` bins, starting at `start_date + start_test_day` days, and stopping when the largest horizon would pass the end of the test period.

#### Scenario: Window count for default config
- **WHEN** the test period is 14 days of 48 bins, the largest horizon is 12 bins and stride is 1 bin
- **THEN** exactly 660 forecast windows are run

### Requirement: Context window
Each forecast SHALL use as context the rows of all selected stops in the 7 days (`7 * 24 * 60 / freq` bins) immediately before the forecast time, containing the target and past covariates, and no row at or after the forecast time.

#### Scenario: No leakage
- **WHEN** a window is forecast at time `t`
- **THEN** every context row has `timestamp < t` and `timestamp >= t - 7 days`

### Requirement: Forecast length and horizon scoring
Each forecast SHALL predict `prediction_length + 1` bins, with quantiles 0.1, 0.5 and 0.9 and cross-learning across stops enabled. A horizon of `h` minutes SHALL be scored against the forecast row whose timestamp equals forecast time plus `h` minutes, so the first predicted bin is not scored.

#### Scenario: Horizon alignment
- **WHEN** the forecast time is `t` and horizon is 30 minutes with 30-minute bins
- **THEN** the prediction and truth compared are those at `t + 30 min`, the second predicted bin

#### Scenario: Missing truth
- **WHEN** a window has no ground-truth rows for a configured horizon
- **THEN** the run fails with an error naming the window time and horizon

### Requirement: Reproducibility
The system SHALL seed random number generators from the configured seed before inference.

#### Scenario: Seed applied
- **WHEN** a run starts with `seed: 42`
- **THEN** torch and numpy generators are seeded with 42 before the first forecast

### Requirement: Persisted outputs
The system SHALL write per-window forecasts (item, forecast time, timestamp, median, 0.1 and 0.9 quantiles, truth) to parquet and a metrics summary to JSON under `data/processed/zero_shot/<year>/`.

#### Scenario: Re-scoring without rerun
- **WHEN** a run completes
- **THEN** the forecasts parquet contains every scored window and horizon, and the summary can be recomputed from it alone with the same values
