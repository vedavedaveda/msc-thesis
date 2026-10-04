"""
Data pipeline for the Copenhagen disruption ABM.

Computes the Rec∩Affected population, builds the shock-day behaviour target,
runs RAPTOR routing for all agents (incremental cache), and saves
outputs.

Run from the project root:
    source .venv/bin/activate
    python -m utils.run_calibration                  # November (default)
    INCIDENT=APRIL python -m utils.run_calibration   # April

Outputs written to outputs/{incident}/:
    rec_aff.csv  — Rec∩Affected reference-day trips
    target.csv   — per-agent behaviour on the shock day
    raptor.pkl   — RAPTOR travel-time results (incremental cache)

Model fitting (model.pkl) is done in calibration_quiters_stayers.ipynb,
which reads rec_aff.csv + raptor.pkl produced here.
"""

import os, sys, pickle, random, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

# ── Path setup (works both as `python -m utils.run_calibration` and directly) ─
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from loguru import logger as _lg
_lg.remove()
_lg.add(lambda msg: None, level='WARNING')

from utils.config import get_incident, SEED
from utils.simulation_utils import build_rec_affected, build_target, simulate_pax, build_timetables

# ── Incident selector ─────────────────────────────────────────────────────────
INCIDENT = os.environ.get('INCIDENT', 'NOVEMBER').upper()
cfg      = get_incident(INCIDENT)
OUT_DIR  = os.path.join('outputs', INCIDENT.lower())

print(f"Incident : {INCIDENT}")
print(f"Output   : {OUT_DIR}/")
os.makedirs(OUT_DIR, exist_ok=True)

random.seed(SEED)
np.random.seed(SEED)

# ── 1. Load trips ─────────────────────────────────────────────────────────────
print(f"\nLoading trips from {cfg['trips_csv']} …")
trips = pd.read_csv(cfg['trips_csv'], low_memory=False)
trips['Start_Time'] = pd.to_datetime(trips['Start_Time'])
trips['End_Time']   = pd.to_datetime(trips['End_Time'])
if 'hour' not in trips.columns:
    trips['hour'] = trips['Start_Time'].dt.hour
print(f"  {len(trips):,} rows, {trips['Kortnr_Kryp'].nunique():,} unique pids")

# ── 2. Rec∩Affected ───────────────────────────────────────────────────────────
print("\nComputing Rec∩Affected population …")
rec_aff, dsb_recurrent_ids = build_rec_affected(trips, cfg)
print(f"  {len(dsb_recurrent_ids):,} agents qualify")

rec_aff_path = cfg['rec_aff_csv']
rec_aff.to_csv(rec_aff_path, index=False)
print(f"  Saved → {rec_aff_path}")

# ── 3. Behaviour target ───────────────────────────────────────────────────────
print("\nBuilding behaviour target …")
target = build_target(trips, dsb_recurrent_ids, cfg)

counts = target['behaviour'].value_counts()
print(f"  Behaviour on {cfg['shock_day']}:")
for beh, n in counts.items():
    print(f"    {beh:<15}: {n:>5,}  ({n/len(target):.1%})")

target_path = cfg['target_csv']
target.to_csv(target_path)
print(f"  Saved → {target_path}")

# ── 4. Load timetables ────────────────────────────────────────────────────────
print("\nLoading timetable …")
baseline_tt, dis_tt = build_timetables(cfg)

# ── 5. RAPTOR simulation (incremental cache) ──────────────────────────────────
raptor_path    = cfg['raptor_cache']
cached_results = []
cached_pids    = set()

if os.path.exists(raptor_path):
    with open(raptor_path, 'rb') as f:
        cached_results = pickle.load(f)
    cached_pids = {str(r['pid']) for r in cached_results}
    print(f"\nCache: {len(cached_results):,} results loaded from {raptor_path}")
else:
    print(f"\nNo cache at {raptor_path} — simulating all agents.")

pids_needed = sorted(dsb_recurrent_ids - cached_pids)
print(f"Agents to simulate: {len(pids_needed):,}  "
      f"(cache covers {len(cached_pids & dsb_recurrent_ids):,} / {len(dsb_recurrent_ids):,})")

new_results = []
n = len(pids_needed)
for i, pid in enumerate(pids_needed):
    if i % 200 == 0 and n > 0:
        print(f"  {i:>5}/{n}  ({i/n:.0%})", flush=True)
    res = simulate_pax(pid, baseline_tt, dis_tt, trips, cfg=cfg)
    if res is None:
        continue
    res['pid'] = pid
    new_results.append(res)

all_cache = cached_results + new_results
if new_results:
    with open(raptor_path, 'wb') as f:
        pickle.dump(all_cache, f)
    print(f"Cache updated: {len(all_cache):,} total → {raptor_path}")
else:
    print("No new agents — cache unchanged.")

# ── 6. Summary ────────────────────────────────────────────────────────────────
sim_df = pd.DataFrame([r for r in all_cache if str(r['pid']) in dsb_recurrent_ids])
label_map = {str(pid): (1 if row['behaviour'] == 'quit' else 0)
             for pid, row in target.iterrows()}
sim_df['label'] = sim_df['pid'].astype(str).map(label_map)
sim_df = sim_df.dropna(subset=['label'])
sim_df['label'] = sim_df['label'].astype(int)

print(f"\nSummary")
print(f"  Coverage  : {len(sim_df):,} / {len(dsb_recurrent_ids):,}  "
      f"({len(sim_df)/len(dsb_recurrent_ids):.1%})")
print(f"  Quit      : {sim_df['label'].sum():,}  ({sim_df['label'].mean():.1%})")
print(f"  Traveller : {(sim_df['label']==0).sum():,}  ({(sim_df['label']==0).mean():.1%})")
print(f"\nDone. Notebooks read from {OUT_DIR}/")
