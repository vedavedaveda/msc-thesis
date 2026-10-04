"""
Core simulation utilities: RAPTOR routing wrappers, substitutability score,
Rec-Affected population construction, feature matrix assembly, and MLE helpers.

All RAPTOR queries go through _run_raptor(), which wraps pyraptor and enforces
the MAX_DELTA_MIN / MAX_DELTA_TRIPS caps defined in config.py.
The substitutability() function implements the log-sum formula:
    S_i = 1 / (ln(exp(beta_t*dt + beta_n*dn) + 1) + 1)
"""

import pickle
import signal
import numpy as np
import pandas as pd
from scipy.special import expit
from sklearn.metrics import roc_curve
from pyraptor.model.structures import Routes, Timetable
from pyraptor.model.raptor import RaptorAlgorithm, best_stop_at_target_station, reconstruct_journey
from pyraptor.dao import read_timetable

from utils.config import (
    SEED, RAPTOR_ROUNDS, MAX_DELTA_MIN, MAX_DELTA_TRIPS,
    BETA_T, BETA_N, S_TRAIN_HINTS, REGIONAL_IC_HINTS,
    MIN_REF_DAYS, MIN_OD_DAYS, MAX_DEP_SPREAD, DSB_FRAC_THR,
    NOV,
)

# ── Backward-compatible re-exports (November defaults) ────────────────────────
# Notebooks importing `from utils.simulation_utils import REF_DAYS, ...` keep working.
# For April processing pass cfg=APR explicitly to each function.
REF_DAYS        = NOV['ref_days']
REF_DAY_ORDER   = NOV['ref_day_order']
DISRUPTED_HOURS = NOV['disrupted_hours']
SAMPLE_SIZE     = 100

# ── Utility functions ────────────────────────────────────────────────────────
def substitutability(df, beta_t=BETA_T, beta_n=BETA_N):
    """
    van Wee et al. LogSum substitutability.
    Returns 1 when no disruption, → 0 as disruption → ∞.
    """
    V_pref = -beta_t * df['baseline'].values - beta_n * df['base_trips'].values
    V_alt  = -beta_t * df['disrupted'].values - beta_n * df['dis_trips'].values
    drop   = np.logaddexp(V_pref, V_alt) - V_alt
    # return np.log(2) / np.maximum(drop, 1e-9)
    return 1 / (np.maximum(drop, 1e-9) + 1)

def nll(params, X, y):
    """
    Negative log-likelihood for logistic regression (matrix form).
    params[0] = intercept; params[1:] = coefficients.
    X: (n, k) array; y: (n,) binary array.
    """
    logit = X @ params[1:] + params[0]
    p = np.clip(expit(logit), 1e-9, 1 - 1e-9)
    return -np.sum(y * np.log(p) + (1 - y) * np.log(1 - p))


def youden_threshold(p_tr, y_tr):
    """Train-set Youden's J threshold: argmax(TPR − FPR)."""
    fpr, tpr, thr = roc_curve(y_tr, p_tr)
    j = tpr - fpr
    return thr[np.argmax(j)]


def format_trip_row(r):
    """
    One-line trip summary for the agent inspector.
    Uses StopIdSequence to show transfer stops when available.
    """
    dep   = r['Start_Time'].strftime('%H:%M')
    dsb   = ' [DSB]' if 'DSB' in str(r['ContractorSequence']) else ''
    tt    = f"{r['TT(min)']:.0f}min"
    stops = [s.strip() for s in str(r['StopIdSequence']).split(';')]
    modes = str(r['ModeSeq']).split('-')
    if len(stops) == len(modes) and len(stops) > 1:
        parts = []
        for i, (stop, mode) in enumerate(zip(stops, modes)):
            if i < len(stops) - 1:
                parts.append(f"{stop} [{mode}]")
            else:
                parts.append(stop)
        route = ' → '.join(parts)
    else:
        route = f"{r['origin_n']} → {r['destination_n']}  [{r['ModeSeq']}]"
    return f"    {dep}  {route}  {tt}{dsb}"


def build_feat_df(sim_df, trips, cfg=None):
    """
    Per-agent trip-level features from reference-day taps.
    Pre-groups trips once for ~100x speedup over the original per-agent scan.

    Parameters
    ----------
    sim_df : DataFrame  with a 'pid' column (agents to compute features for)
    trips  : DataFrame  full trip records
    cfg    : dict       incident config from utils.config (NOV or APR).
                        Defaults to November if None.

    Returns
    -------
    DataFrame indexed by pid with columns:
        dep_std, dep_mean, dsb_frac, n_modes_real, ref_tt_real, n_ref_days, tog_first
    """
    ref_days        = cfg['ref_days']        if cfg else REF_DAYS
    disrupted_hours = cfg['disrupted_hours'] if cfg else DISRUPTED_HOURS

    pids_in_sim = set(sim_df['pid'].astype(str))

    ref = trips[
        trips['date'].isin(ref_days) &
        trips['hour'].isin(disrupted_hours)
    ].copy()
    ref['dep_min'] = (pd.to_datetime(ref['Start_Time']).dt.hour * 60 +
                      pd.to_datetime(ref['Start_Time']).dt.minute)

    records = []
    for pid, grp in ref.groupby('Kortnr_Kryp'):
        if str(pid) not in pids_in_sim:
            continue
        grp_sorted = grp.sort_values('Start_Time')
        first_dep  = grp_sorted.groupby('date')['dep_min'].first()
        first_mode = grp_sorted.groupby('date')['ModeSeq'].first()

        n_tog     = first_mode.apply(lambda m: str(m).split('-')[0].strip() == 'Tog').sum()
        tog_first = float(n_tog >= len(first_mode) / 2)

        records.append({
            'pid':          str(pid),
            'dep_std':      first_dep.std() if len(first_dep) > 1 else 0.0,
            'dep_mean':     first_dep.mean(),
            'dsb_frac':     grp['ContractorSequence'].apply(
                                lambda x: 1 if 'DSB' in str(x) else 0).mean(),
            'n_modes_real': grp['ModeSeq'].apply(
                                lambda x: len(str(x).split('-')) - 1).mean(),
            'ref_tt_real':  grp['TT(min)'].mean(),
            'n_ref_days':   grp['date'].nunique(),
            'tog_first':    tog_first,
        })

    feat_df = pd.DataFrame(records).set_index('pid')
    feat_df['dep_std'] = feat_df['dep_std'].fillna(0.0)
    return feat_df


def build_rec_affected(trips, cfg):
    """
    Compute the Rec∩Affected population from a trips DataFrame.

    Filters applied (all thresholds from utils.config):
      1. Passenger present on ALL MIN_REF_DAYS reference Mondays.
      2. Specific OD recurs on >= MIN_OD_DAYS reference days.
      3. Departure spread across ref days <= MAX_DEP_SPREAD minutes.
      4. Qualifying DSB fraction >= DSB_FRAC_THR.
      5. Mean departure in [dep_hour_min, dep_hour_max) hours.

    Parameters
    ----------
    trips : DataFrame  — all trip records (ref days + shock day)
    cfg   : dict       — incident config from utils.config (NOV or APR)

    Returns
    -------
    rec_aff          : DataFrame of reference-day trips for Rec∩Affected agents
    dsb_recurrent_ids: set of str pids
    """
    ref_days        = cfg['ref_days']
    disrupted_hours = cfg['disrupted_hours']
    dep_min_lo      = cfg['dep_hour_min'] * 60
    dep_min_hi      = cfg['dep_hour_max'] * 60

    # Step 1: reference-day trips only
    ref = trips[trips['date'].isin(ref_days)].copy()

    # Step 2: keep pids present on ALL reference days
    pid_day_counts = ref.groupby('Kortnr_Kryp')['date'].nunique()
    pids_all_days  = set(pid_day_counts[pid_day_counts == MIN_REF_DAYS].index)
    ref = ref[ref['Kortnr_Kryp'].isin(pids_all_days)]

    # Step 3: first trip per (pid, oc, dc, date) within disrupted hours
    ref_am = (ref[ref['hour'].isin(disrupted_hours)]
              .dropna(subset=['oc', 'dc'])
              .copy())
    ref_am['dep_min'] = (pd.to_datetime(ref_am['Start_Time']).dt.hour * 60 +
                         pd.to_datetime(ref_am['Start_Time']).dt.minute)

    first_od = (ref_am.sort_values('Start_Time')
                .groupby(['Kortnr_Kryp', 'oc', 'dc', 'date'], as_index=False)
                .first())

    def _qualifying_dsb(row):
        if 'DSB' not in str(row['ContractorSequence']): return False
        modes = str(row['ModeSeq']).split('-')
        if len(modes) > 1 and modes[-1] == 'Tog' and 'Tog' not in modes[:-1]: return False
        return True

    first_od['qualifying_dsb'] = first_od.apply(_qualifying_dsb, axis=1)

    # Step 4: OD-level statistics
    od_stats = (first_od
                .groupby(['Kortnr_Kryp', 'oc', 'dc'])
                .agg(
                    n_days       = ('date',           'nunique'),
                    min_dep_min  = ('dep_min',        'min'),
                    max_dep_min  = ('dep_min',        'max'),
                    mean_dep_min = ('dep_min',        'mean'),
                    dsb_frac     = ('qualifying_dsb', 'mean'),
                )
                .reset_index())

    # Step 5: Rec∩Affected filter
    rec_aff_ods = od_stats[
        (od_stats['n_days']                                    >= MIN_OD_DAYS)  &
        (od_stats['max_dep_min'] - od_stats['min_dep_min']    <= MAX_DEP_SPREAD) &
        (od_stats['dsb_frac']                                 >= DSB_FRAC_THR)  &
        (od_stats['mean_dep_min']                             >= dep_min_lo)    &
        (od_stats['mean_dep_min']                             <  dep_min_hi)
    ]

    rec_aff = (first_od
               .merge(rec_aff_ods[['Kortnr_Kryp', 'oc', 'dc']],
                      on=['Kortnr_Kryp', 'oc', 'dc'], how='inner')
               .drop(columns=['dep_min', 'qualifying_dsb'])
               .merge(rec_aff_ods[['Kortnr_Kryp', 'oc', 'dc',
                                   'n_days', 'mean_dep_min', 'dsb_frac']],
                      on=['Kortnr_Kryp', 'oc', 'dc'], how='left'))

    dsb_recurrent_ids = set(rec_aff['Kortnr_Kryp'].astype(str).unique())
    return rec_aff, dsb_recurrent_ids


def build_target(trips, rec_aff_ids, cfg):
    """
    Classify each Rec∩Affected agent's behaviour on the shock day.

    Parameters
    ----------
    trips        : DataFrame  — all trip records
    rec_aff_ids  : set of str — pids in the Rec∩Affected population
    cfg          : dict       — incident config from utils.config (NOV or APR)

    Returns
    -------
    DataFrame indexed by pid with columns:
        oc_ref, dc_ref, oc_shock, dc_shock, ModeSeq, ContractorSequence, behaviour
    Behaviour values: 'quit' | 'same_od' | 'same_origin' | 'rerouted'
    """
    ref_days        = cfg['ref_days']
    shock_day       = cfg['shock_day']
    disrupted_hours = cfg['disrupted_hours']

    # Canonical OD: most frequent (oc, dc) pair on reference days in disrupted hours
    ref = trips[
        trips['date'].isin(ref_days) &
        trips['Kortnr_Kryp'].astype(str).isin(rec_aff_ids) &
        trips['hour'].isin(disrupted_hours)
    ].copy()
    ref['oc'] = pd.to_numeric(ref['oc'], errors='coerce').astype('Int64')
    ref['dc'] = pd.to_numeric(ref['dc'], errors='coerce').astype('Int64')

    canonical = (ref
                 .groupby(['Kortnr_Kryp', 'oc', 'dc']).size()
                 .reset_index(name='days')
                 .sort_values('days', ascending=False)
                 .drop_duplicates('Kortnr_Kryp')
                 .set_index('Kortnr_Kryp'))

    # Shock-day first AM trip
    shock = trips[
        (trips['date'] == shock_day) &
        (trips['Kortnr_Kryp'].astype(str).isin(rec_aff_ids))
    ].copy()
    shock['oc'] = pd.to_numeric(shock['oc'], errors='coerce').astype('Int64')
    shock['dc'] = pd.to_numeric(shock['dc'], errors='coerce').astype('Int64')

    shock_am = (shock[shock['hour'].isin(disrupted_hours)]
                .sort_values('Start_Time')
                .groupby('Kortnr_Kryp')
                .first()[['oc', 'dc', 'ModeSeq', 'ContractorSequence']])

    target = canonical[['oc', 'dc']].join(
        shock_am, how='left', lsuffix='_ref', rsuffix='_shock')

    def _classify(row):
        if pd.isna(row['oc_shock']):  return 'quit'
        if row['oc_shock'] == row['oc_ref']:
            return 'same_od' if row['dc_shock'] == row['dc_ref'] else 'same_origin'
        return 'rerouted'

    target['behaviour'] = target.apply(_classify, axis=1)
    return target

_CLUSTER_CSV = 'data/geospatial/stop_to_cluster_with_plot_status.csv'
_CLUSTER_MAP: dict = {}   # populated by build_cluster_map(); shared across timetables


def build_cluster_map(timetable, cluster_csv: str = _CLUSTER_CSV) -> dict:
    """
    Build and cache a mapping from rejsekort cluster_id (int) → list[Stop].

    GTFS stop_ids look like '000008600716'; the cluster CSV uses the bare
    numeric string '8600716'.  We normalise by stripping leading zeros.
    """
    global _CLUSTER_MAP
    sc = pd.read_csv(cluster_csv, usecols=['stop_id_clean', 'cluster_id'])
    sc['stop_id_clean'] = sc['stop_id_clean'].astype(str)
    clean_to_cid = dict(zip(sc['stop_id_clean'], sc['cluster_id'].astype(int)))

    result: dict = {}
    for stop_id_raw, stop in timetable.stops.set_idx.items():
        clean = str(stop_id_raw).lstrip('0') or '0'
        cid   = clean_to_cid.get(clean)
        if cid is not None:
            result.setdefault(cid, []).append(stop)

    _CLUSTER_MAP = result
    return result


def build_timetables(cfg):
    full_tt         = read_timetable(cfg['timetable_folder'])
    disrupted_hints = {h.upper() for h in cfg['disrupted_hints']}   # case-insensitive
    base_routes, dis_routes = Routes(), Routes()
    for trip in full_tt.trips:
        base_routes.add(trip)
        if str(trip.hint).upper() not in disrupted_hints:
            dis_routes.add(trip)
    kw = dict(stations=full_tt.stations, stops=full_tt.stops, trips=full_tt.trips,
              trip_stop_times=full_tt.trip_stop_times, transfers=full_tt.transfers)
    return Timetable(**kw, routes=base_routes), Timetable(**kw, routes=dis_routes)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _stops_for_cluster(cluster_id, timetable):
    """Return Stop objects for a rejsekort cluster_id using the cached cluster map."""
    if _CLUSTER_MAP:
        return _CLUSTER_MAP.get(int(cluster_id), [])
    # fallback: station-name index (works for name-keyed timetables)
    station = timetable.stations.set_idx.get(cluster_id)
    return list(station.stops) if station is not None else []

def _run_raptor(timetable, origin_stops, dest_stops, dep_seconds, timeout_sec=120):
    def _timeout_handler(signum, frame):
        raise TimeoutError("RAPTOR exceeded time limit")
    best = None
    for dep in dep_seconds:
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(timeout_sec)
        try:
            raptor = RaptorAlgorithm(timetable)
            bag    = raptor.run(origin_stops, dep, RAPTOR_ROUNDS)
            bs     = best_stop_at_target_station(dest_stops, bag[RAPTOR_ROUNDS])
            if bs != 0:
                j = reconstruct_journey(bs, bag[RAPTOR_ROUNDS])
                if j.is_valid() and len(j) > 0:
                    if best is None or j.travel_time() < best.travel_time():
                        best = j
        except TimeoutError:
            pass
        finally:
            signal.alarm(0)
    return best

def _journey_minutes(journey):
    return journey.travel_time() / 60.0 if journey is not None else None

def _journey_trips(journey):
    return journey.number_of_trips() if journey is not None else None

def get_canonical_trip(pid, trips, cfg=None):
    ref_day_order   = cfg['ref_day_order']   if cfg else REF_DAY_ORDER
    disrupted_hours = cfg['disrupted_hours'] if cfg else DISRUPTED_HOURS

    pax_trips = trips[trips['Kortnr_Kryp'] == pid]
    od_counts, day_ods = {}, {}
    for day in ref_day_order:
        day_df = pax_trips[
            (pax_trips['date'] == day) & (pax_trips['hour'].isin(disrupted_hours))
        ]
        for _, row in day_df.iterrows():
            try:
                oc, dc = int(row['oc']), int(row['dc'])
            except (ValueError, TypeError):
                continue
            od = (oc, dc)
            od_counts[od] = od_counts.get(od, 0) + 1
            day_ods.setdefault(day, []).append((od, row))

    canonical_ods = {od for od, cnt in od_counts.items() if cnt >= 2}
    if not canonical_ods:
        return None

    for day in ref_day_order:
        for od, row in day_ods.get(day, []):
            if od in canonical_ods:
                dep_dt = pd.to_datetime(row['Start_Time'], errors='coerce')
                if pd.isna(dep_dt):
                    continue
                dep_sec = dep_dt.hour * 3600 + dep_dt.minute * 60 + dep_dt.second
                return (od[0], od[1], dep_sec)
    return None

def simulate_pax(pid, baseline_tt, dis_tt, trips, cfg=None):
    canonical = get_canonical_trip(pid, trips, cfg=cfg)
    if canonical is None:
        return None
    oc, dc, dep_sec = canonical

    origin_stops = _stops_for_cluster(oc, baseline_tt)
    dest_stops   = _stops_for_cluster(dc, baseline_tt)
    if not origin_stops or not dest_stops:
        return None

    baseline_j    = _run_raptor(baseline_tt, origin_stops, dest_stops, [dep_sec])
    baseline_min  = _journey_minutes(baseline_j)
    baseline_trps = _journey_trips(baseline_j)
    if baseline_min is None:
        return None

    dis_origin  = _stops_for_cluster(oc, dis_tt)
    dis_dest    = _stops_for_cluster(dc, dis_tt)
    dis_j       = _run_raptor(dis_tt, dis_origin, dis_dest, [dep_sec])
    dis_min     = _journey_minutes(dis_j)
    dis_trps    = _journey_trips(dis_j)

    if dis_min is None:
        dis_min  = baseline_min  + MAX_DELTA_MIN
        dis_trps = baseline_trps + MAX_DELTA_TRIPS

    return {
        'delta':       dis_min  - baseline_min,
        'baseline':    baseline_min,
        'disrupted':   dis_min,
        'delta_trips': dis_trps - baseline_trps,
        'base_trips':  baseline_trps,
        'dis_trips':   dis_trps,
    }
