# Spec Delta

## Purpose

Compute point and interval forecast metrics exactly as the mobility-baselines reference does, so results are comparable to the paper.

## ADDED Requirements

### Requirement: Point metrics
The system SHALL compute MAE and RMSE over all points of a window and horizon without masking, and MAPE only over points whose truth is greater than zero.

#### Scenario: Zero truth in MAPE
- **WHEN** some truth values are 0
- **THEN** those points are excluded from MAPE but included in MAE and RMSE

#### Scenario: Known values
- **WHEN** truth is [1, 2, 4] and predictions are [2, 2, 2]
- **THEN** MAE is 1, RMSE is sqrt(5/3) and MAPE is mean(1, 0, 0.5)

### Requirement: Interval metrics
The system SHALL compute coverage as the share of truth values inside the closed interval between the 0.1 and 0.9 quantile forecasts, and report the mean interval width under the name `IQR_MEAN`.

#### Scenario: Coverage
- **WHEN** 3 of 4 truth values lie within their [0.1, 0.9] interval
- **THEN** coverage is 0.75

### Requirement: Aggregation
The system SHALL compute each metric per window and horizon, average across windows to get a per-horizon value, and average per-horizon values to get the overall value. Per-window values SHALL NOT be pooled.

#### Scenario: Mean of RMSEs
- **WHEN** two windows have RMSE 1 and 3 at one horizon
- **THEN** the horizon RMSE is 2, not the RMSE of the pooled points
