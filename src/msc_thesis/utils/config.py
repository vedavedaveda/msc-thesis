"""
Central configuration for the Copenhagen disruption ABM.
All notebooks and scripts import from here — never hardcode these values.
"""

# ── Shared constants ───────────────────────────────────────────────────────────
SEED            = 42
RAPTOR_ROUNDS   = 3
MAX_DELTA_MIN   = 90        # RAPTOR: max tolerable extra travel time (min)
MAX_DELTA_TRIPS = 5         # RAPTOR: max tolerable extra boardings
BETA_T          = 0.10      # DCM disutility per minute
BETA_N          = 0.50      # DCM disutility per boarding

# Recurrent + Affected filter thresholds (must be identical for both incidents)
MIN_REF_DAYS    = 3         # passenger must appear on ALL reference Mondays
MIN_OD_DAYS     = 2         # specific OD must recur on ≥ this many ref days
MAX_DEP_SPREAD  = 60        # max departure spread across ref days (min)
DSB_FRAC_THR    = 0.50      # minimum DSB qualifying-trip fraction

# Route hint sets
S_TRAIN_HINTS     = {'A', 'B', 'Bx', 'C', 'E', 'F', 'H'}
REGIONAL_IC_HINTS = {'IC', 'ICL', 'RE', 'IL'}

# ── November 5th 2018 ─────────────────────────────────────────────────────────
NOV = dict(
    ref_days        = {'08OCT2018', '22OCT2018', '29OCT2018'},
    ref_day_order   = ['29OCT2018', '22OCT2018', '08OCT2018'],
    shock_day       = '05NOV2018',
    disrupted_hours = {7, 8},
    dep_hour_min    = 7,         # affected window start (inclusive)
    dep_hour_max    = 9,         # affected window end   (exclusive)
    disrupted_hints = S_TRAIN_HINTS,
    timetable_folder= 'data/GTFS_NOV2018',
    trips_csv       = 'data/trips/recurrent_traveler_trips.csv',
    rec_aff_csv     = 'outputs/november/rec_aff.csv',
    raptor_cache    = 'outputs/november/raptor.pkl',
    target_csv      = 'outputs/november/target.csv',
    model_pkl       = 'outputs/november/model.pkl',
    clusters_csv    = 'outputs/november/clusters.csv',
    predictions_csv = 'outputs/november/predictions.csv',
    output_plot     = 'outputs/november/calibration_results.png',
)

# ── April 1st 2019 ────────────────────────────────────────────────────────────
APR = dict(
    ref_days        = {'11MAR2019', '18MAR2019', '25MAR2019'},
    ref_day_order   = ['25MAR2019', '18MAR2019', '11MAR2019'],
    shock_day       = '01APR2019',
    disrupted_hours = {6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16},
    dep_hour_min    = 6,         # affected window start (inclusive)
    dep_hour_max    = 16,        # affected window end   (exclusive)
    disrupted_hints = S_TRAIN_HINTS | REGIONAL_IC_HINTS,
    timetable_folder= 'data/GTFS_APR2019',
    trips_csv       = 'data/trips/recurrent_traveler_trips_apr01.csv',
    rec_aff_csv     = 'outputs/april/rec_aff.csv',
    raptor_cache    = 'outputs/april/raptor.pkl',
    target_csv      = 'outputs/april/target.csv',
    model_pkl       = 'outputs/april/model.pkl',
    clusters_csv    = 'outputs/april/clusters.csv',
    predictions_csv = 'outputs/april/predictions.csv',
    output_plot     = 'outputs/april/calibration_results.png',
)

# ── Selector ──────────────────────────────────────────────────────────────────
INCIDENTS = {'NOVEMBER': NOV, 'APRIL': APR}

def get_incident(name: str) -> dict:
    """Return config dict for 'NOVEMBER' or 'APRIL'."""
    key = name.strip().upper()
    if key not in INCIDENTS:
        raise ValueError(f"Unknown incident {key!r}. Choose from {list(INCIDENTS)}")
    return INCIDENTS[key]
