# Zero-shot analysis plan (RQ1)

How we propose to evaluate Chronos-2 zero-shot forecasts on Rejsekort data, to answer RQ1: *does
zero-shot accuracy get worse during special events than in routine periods, and does that depend on
event type and size?* Sections 1-2 are the short version; section 3 is the full specification.

## 1. Overview

**Two parts.** First we measure how good zero-shot is on ordinary days, against simple baselines.
Then we measure how much worse it gets around events, relative to that.

**The core comparison.** For every large event, we compare the forecast error at stops near the
venue with the error at the *same stops, same weekday and time* in normal weeks. Error grows with
passenger volume anyway, and some days are bad everywhere (rain, a network disruption). So we
divide by the same comparison at unaffected stops on the same day:

```
                    event day         normal weeks (same weekday and time)
stops near venue    error        ÷    error                 = R      worse at the venue?
unaffected stops    error        ÷    error                 = R_ref  worse everywhere that day?

                    R* = R / R_ref    (above 1 = degradation caused by the event)
```

To check that any degradation is the model's fault and not just a surprise no model could
foresee, we also compare Chronos with a simple seasonal baseline on the same bins.

**The three questions we test** (fixed in advance; everything else is exploratory):

1. Is the error higher when people arrive at and leave events?
2. Is it mainly higher when the forecast was made *before* the event started? After it starts,
   the model can see it in its input.
3. Does the degradation grow with event size?

**Safeguards.**

- Events are chosen by RSVP count, never by whether demand visibly changed. Selecting on the
  outcome would make question 1 true by construction.
- Fake "events" on normal days must show no effect; if they do, the method is biased.
- We develop the analysis on 20% of the events and run it once, frozen, on the other 80%.
- Missing data is detected and excluded, because the stop series fills gaps with zeros, which
  look like a drop in demand.

**What we report.**

- A routine table: zero-shot skill against the baselines, by horizon, hour, stop size and mode.
- The main figure: error ratio against time relative to event start, split by whether the
  forecast was made before or after the start, next to the demand ratio.
- The effect of event size and venue type, with uncertainty computed over events.
- Calibration (how often the truth falls inside the intervals), routine vs event.
- The reference benchmark's metrics (MAE, RMSE, MAPE, coverage), for comparability.

## 2. Open choices

Where the plan has to pick between reasonable options. Each row has a proposal; the rest of this
page assumes it.

| Choice | Option A | Option B | Proposal |
|---|---|---|---|
| Headline error measure | Pinball loss over all 21 quantiles (scores the whole forecast distribution) | MAE (closest to the reference benchmark) | A, with B as a robustness check |
| Primary RQ1 quantity | Error ratio `R*` ("how much worse during events") | Skill gap vs seasonal baseline ("does Chronos lose its edge") | A (matches the RQ wording), B reported next to it |
| What counts as routine | Strict: no event at all nearby | Lenient: small events (< 100 attending) allowed | B; strict as a sensitivity check (strict leaves the centre with almost no controls) |
| Stop distance to venue | Straight-line | Walking distance | A; B as a check on the largest events |
| Hubs with no unaffected stop to compare | Relax the matching | Skip the correction for those events | A; report how often it was needed |
| Chronos `cross_learning` | On (reference setting; forecasts depend on the stop set) | Off (stops forecast independently) | A, with B as an ablation |
| Size of overlapping events | Max of the sub-events | Sum | A (sum double counts sub-events) |

## 3. Specification

### 3.1 Measures

- **Cell** = (stop, target bin, forecast origin). **Loss** = mean pinball loss over the 21
  quantile levels (≈ CRPS / 2); MAE of the median as the robustness loss.
- **Excess loss ratio**, per event cluster `e` and phase `p`:

  ```
  R(e,p)   = sum of loss on exposed cells / mean over matched controls of the same sum
  R*(e,p)  = R(e,p) / R_ref(e,p)
  ```

  Ratios of sums within one stop and time of day are scale-free. Sums avoid near-zero per-cell
  losses.
- **Demand ratio** `D(e,p)`: the same ratio on truth. It measures the size of the surprise.
- **Skill gap** `ΔS = S_exposed − S_control`, with `S = 1 − L_chronos / L_seasonal_quantile`.
- **Hypotheses**, Holm-corrected at α = 0.05:
  - **H1:** `log R* > 0` in arrival and egress;
  - **H2:** the effect is larger for *blind* origins (before arrival starts) than for *informed*
    ones;
  - **H3:** `log R*` increases with `log(n_attending)`.

### 3.2 Data and forecasts

- **Data checks first.** Flag stop-days with runs of zero bins during service hours at normally
  busy stops, and network days far below their matched days. Flagged cells are excluded from
  every slice. Thresholds are set on the pilot.
- **Range.** Rolling origins, stride 1 bin, 2017-03-22 (after 7 days of context) to 2017-11-12
  (catalog coverage end). Zero-shot needs no training split, so RQ1 uses the whole range. The
  shared cross-model test split is a subset of it, reported separately.
- **Stops.** Top 250 by volume, plus every ring-0 stop of an event ≥ 100, plus the reference
  stops. Fixed from the event mask before any run.
- **Runs.** Two runs, target `check_ins` and target `check_outs`, each with the other channel as
  past covariate. 21 quantiles, raw output, step 2 forecast contract.
- **Ablations.** 28-day context (repeats H1, H2 and the echo phase); `cross_learning: false`.
- **Baselines.**
  - *Seasonal quantile*: empirical 21 quantiles of the same stop, weekday and bin over the
    previous 6 valid weeks.
  - *Seasonal naive*: 7 days, point only.

### 3.3 Routine performance

- **Routine bins:** not a calendar exclusion, not flagged, no event ≥ 100 in the stop's ring 0
  in the bin or its context window, before 2017-11-12.
- **Report:**
  - pinball and MAE skill against both baselines, overall and by horizon, hour, weekday/weekend,
    stop volume quartile and mode;
  - the per-stop skill distribution, with fan plots for the 10 worst stops;
  - coverage at 50/80/90/98% and the randomized PIT histogram.
- **Uncertainty:** block bootstrap over days.

### 3.4 Events

- **Event set.** Size by `n_attending`, in classes 100-299, 300-999 and ≥ 1000 (the hand-curated
  set). Events under 100 are minor. `generic` locations, `long_running` and `citywide` events are
  excluded (step 3).
- **Clusters.** Sessions with overlapping masks, and `colocated_group` rows, form one cluster.
  Clusters are the statistical unit.
- **Type.** One venue class per event: stadium/arena, concert venue/club, conference/exhibition,
  outdoor/festival, other. Assigned from the venue name and checked against the Facebook
  categories. A class with fewer than 10 clusters is reported descriptively only.
- **Mask.** Stop coordinates come from a 2017 GTFS feed (the configured file is from 2021).
  - Ring 0: rail/metro ≤ 800 m and bus ≤ 400 m from the venue, plus the nearest rail stop.
  - Ring 1: 800-1500 m, for spillover only (exploratory).
- **Phases**, relative to session start `S` and end `E` (`no_end`: `E = S + 3h`):

  | Phase | Bins | Target | Role |
  |---|---|---|---|
  | placebo | [S−6h, S−3h) | both | should give `R* ≈ 1` |
  | arrival | [S−2h, S+30m) | `check_outs` | H1, H2 |
  | during | [S+30m, E−30m) | both | descriptive |
  | egress | [E−30m, E+2h) | `check_ins` | H1, H2 |
  | echo | arrival/egress bins on later days still inside the context window | both | does the spike in the input distort later forecasts? |

- **Origins.** Each is labelled *blind* (before arrival starts) or *informed* (after it).

### 3.5 Controls and reference

- **Calendar exclusions.** Public holidays from the `holidays` package (Easter 13-17 Apr, Store
  Bededag 12 May, Ascension 25 May plus the 26 May bridge day, 5 Jun), school summer and autumn
  holidays from the municipal calendar, and both DST transition days.
- **Matched controls.** Same stop, weekday, bin and horizon, in weeks ±1 to ±6. A control is
  valid if:
  - it is not excluded or flagged;
  - no event ≥ 100 touches the stop's ring 0 in the bin or in the context window before its
    origin.

  At least 3 valid controls are needed per cell; the drop rate is reported.
- **Reference stops.** 20 stops outside every ring 0 at that time, matched on mode and volume
  decile, scored over the same times and control weeks. This gives `R_ref`.
- **Placebo events.** Each cluster gets a copy shifted to a random valid routine day at the same
  venue and time. The placebo copies must give `log R* ≈ 0`.
- **Day-level cases** (public holidays, citywide events). The whole network is exposed, so there
  are no reference stops.
  - `R_day` and `D_day` = the network-wide totals of loss and of truth on the day, each divided
    by the mean over matched routine days.
  - Each case is compared with placebo days, and DMI precipitation on the day is reported.
  - Case studies only, with no hypothesis test.

### 3.6 Statistics

- **Per cluster and phase:** `log R*`, `log D`, `ΔS`, and the coverage gap at 50% and 80%.
- **Summaries:** the mean over clusters, with a 95% CI from a cluster bootstrap (B = 2000).
- **Size and type:** a weighted regression across clusters,
  `log R* ~ log(n_attending) + phase + origin label + venue type + horizon bucket`, with
  bootstrap CIs. DMI precipitation is added as a check.
- **Endogenous severity:** `log R*` against `log D`, as a figure only. It is descriptive,
  because it is derived from the truth.
- **Power check** on the dev clusters, before the confirmatory run. It shows which size
  classes and types can support a claim.

### 3.7 Calibration during events

Coverage at 50/80/90/98% and the randomized PIT histogram, event vs matched control, per phase.
Reported as excess over the routine calibration (section 3.3), since the existing run already
covers only 0.70 at nominal 0.80.

### 3.8 Reference benchmark metrics

The reference benchmark ([arXiv 2602.24238](https://arxiv.org/abs/2602.24238)) reports MAE,
RMSE, MAPE, and the 0.1-0.9 coverage and width.

- **Parity table:** all five, computed the reference way, on the shared test split and overall.
  For comparison with the benchmark only.
- **On the RQ1 slices:** the MAE ratio and the 0.1-0.9 coverage gap (with a width ratio), next
  to the headline.
- **Not used for RQ1 claims:**
  - RMSE, because a few spikes dominate it;
  - MAPE, because dividing by the inflated event truth hides degradation, and it drops zeros;
  - pooled MAE, because it depends on scale.

### 3.9 Order of work

1. **Pilot** on the existing run:
   - the 5 June holiday against the four surrounding Mondays, to test the control code;
   - set the data-check thresholds;
   - measure the control drop rate and reference-stop availability by area.
2. **Look at the raw material.** Fan plots at venue stops for the 20 largest curated events.
   Set the phase lengths here, then freeze them.
3. **Build** clusters, mask, data flags, controls, reference stops and placebo copies.
4. **Split** clusters 20% dev / 80% confirmatory. Develop the evaluator on the dev clusters
   only.
5. **Freeze and commit** this page. Run the routine and confirmatory analyses once. Report any
   later change as a deviation.

Out of scope: aggregation (RQ2), fine-tuning, the GNN and conformal methods.

Relation to [plan.md](plan.md): its logged decisions are binding. This page proposes answers for
open steps 4-8, 10, 11 and 13; plan.md should be updated if we agree.
