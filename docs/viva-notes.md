# Viva notes — India Transit Crowd AI

## 45–60 second project summary

“India Transit Crowd AI is a multimodal Indian transit discovery product built by migrating the existing React, FastAPI and machine-learning project. Prediction is deliberately narrower than the discovery catalog: only Bengaluru Namma Metro/BMRCL is enabled, because it has a reproducible hourly station-wise observed-boardings source with documented ODbL terms. I normalize the source into station-hour records, preserve reported zeros and missing periods, and predict the next observed hour from strictly earlier contiguous history. I compare real regression and classification models using chronological train, validation and test periods; the selected regression estimate is mapped to training-only historical percentiles, while a separately trained classifier is shown as a cross-check. The dashboard also shows observed-only history, station comparisons, sensitivity, recommendations and PCA/DBSCAN profiles. Those relative-demand labels are not train occupancy, safety levels or live crowding.”

## Facts to remember

- **Only enabled family:** Bengaluru · METRO · BMRCL (`bengaluru-namma-metro`).
- **Source:** RTI-sourced station-hour compilation in `Vonter/bmrcl-ridership-hourly`, pinned to commit `6c44579b5ff3428a88bddc44baf84e436a940612`.
- **Source license:** ODbL-1.0; attribution/share-alike and underlying-rights caveats are preserved in `data/licenses/`.
- **Dataset:** 92,280 observed station-hours, 83 stations, 18,200 explicit zero rows, zero missing-hour fills. Windows are August 1–18 and September 1–30, 2025; August 19–31 is absent.
- **Target:** entries/boardings during the station hour, not onboard load, seat availability or physical occupancy.
- **Split:** chronological by unique target hour, 70%/15%/15%; train 43,865 rows, validation 10,126, final test 10,209. Test never selects the winner. Three expanding-window time-series CV folds run inside training.
- **Regression champion:** XGBoost, chosen on validation MAE (RMSE tie-break). Persisted artifact test metrics and the independent replay are in `docs/model_report.md` and the family report JSON.
- **Classification champion:** Random Forest, chosen on validation macro-F1 with HIGH recall tie-break; current test macro-F1 is about 0.769, HIGH recall 0.649, SEVERE recall 0.855.
- **Training-only global threshold cuts:** P50 223, P80 612, P95 1,399 station boardings/hour. Entity thresholds need 500 targets; otherwise family-level (minimum 500) then global fallback.
- **Station analytics:** two-component PCA retains about 0.8999 variance; DBSCAN reports two clusters plus 13 noise points for this training-period fit. These are algorithm outputs, not manually named station types.

## Likely questions

### 1. Why do you say “multimodal” if the model is only for a metro?

The **discovery architecture** is multimodal and catalogs selected bus/metro systems. The **prediction coverage** is not: only one verified metro family has source data and a trained artifact. The product labels every other system as unavailable rather than generalizing BMRCL results to other modes/operators.

### 2. Why is BMRCL the only model family?

The pinned BMRCL source provides a concrete observed station-hour measure, repeatable source file, source documentation and ODbL notice. Other Indian leads have coarser daily/monthly granularity or approval/license/data-access gaps. A source enters the model registry only after its provenance, target semantics, access/license and reproducibility are verified, followed by separate training and evaluation.

### 3. Are GTFS feeds demand data?

No. GTFS Schedule describes transport service—routes, stops, trips and schedules. It does not report the passenger boardings used as the supervised target. GTFS references support network discovery only. Real-time feeds or positions are not assumed available or shown as live.

### 4. What does the LOW/MODERATE/HIGH/SEVERE label mean?

It compares a model estimate with frozen training-only historical demand percentiles. LOW is at or below P50; MODERATE is above P50 through P80; HIGH is above P80 through P95; SEVERE is above P95. There is no capacity or onboard-load field, so these are not physical crowding, safety, or occupancy categories.

### 5. How do you prevent future-data leakage?

For target hour `T`, all boarding features end at `T−1`; calendar fields are known from target time, but no demand observation at `T` enters a feature. Incomplete history across missing hours is dropped, never bridged. Splits are chronological across unique global target times. Thresholds, profile clustering and training medians use training data only.

### 6. Why both a regressor and a classifier?

The regressor provides a numeric estimate and the percentile rules produce the primary documented band. A separate classifier learns the same historical-relative labels and gives an independent check. Its output is presented separately, not substituted silently for the primary threshold rule.

### 7. Why not fill missing hours with zero?

The source distinguishes reported zero ridership from missing station-hour rows. A missing row could mean unavailable or unreported data rather than zero passengers. The adapter preserves the former and leaves the latter absent; affected supervised windows are dropped.

### 8. What does the recommendation show?

It compares the same station's saved model output at eligible nearby hours within ±3 hours. A lower predicted boarding count is only a model estimate; it does not guarantee spare capacity or lower onboard crowding.

### 9. Is the estimate live or for today?

No. The source snapshot ends September 30, 2025. A request after a station's latest source observation is clearly described as a historical-snapshot projection. It is limited to 336 recursive hours and cannot represent current 2026 service conditions.

### 10. What is the product architecture for future modes/operators?

A source adapter maps a verified feed into a shared canonical record contract; the model-family registry binds system ID, city, mode, operator, entity type, measure, timezone and artifact directory. A new family gets its own checks, leakage-safe benchmark and saved output. The current family list contains BMRCL only.

## Demo sequence

1. Open the system catalog; point out that one family has a verified model and other rows are references.
2. Select Delhi Metro or another unsupported system; show its reason and that no station forecast form or old result remains.
3. Return to Bengaluru → Metro → BMRCL; select a listed station and a permitted date/hour.
4. Explain the result as historical station boardings, show the model name, snapshot note, threshold method, classifier check and local sensitivity caveat.
5. Show that observed series and heatmap contain source observations only; missing cells are not zero-filled or blended with model estimates.
6. Show station comparison and PCA/DBSCAN profiles as model-derived historical analytics, not live positions or hand-labeled crowd clusters.

## Reference files

- Source/license: [`dataset.md`](dataset.md), `data/licenses/BMRCL-ATTRIBUTION.md`
- Evaluation: [`model_report.md`](model_report.md)
- Architecture: [`architecture.md`](architecture.md)
- Scope/migration: [`migration.md`](migration.md)
