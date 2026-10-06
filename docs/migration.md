# Migration record: TransitCrowd AI → India Transit Crowd AI

This is a migration of the existing project, not a clean-room rewrite. The prior product used a single US bus-demand scope; that requirement has been superseded by India-focused multimodal discovery with verified prediction initially enabled only for Bengaluru Namma Metro/BMRCL. This section is a historical implementation record, not a description of current support.

## Preserved

- React + TypeScript + Vite frontend structure, responsive editorial visual system, animation/reduced-motion support, custom charts, navigation and reusable UI components.
- The FastAPI service boundary, artifact-backed inference, typed API schemas, health/report endpoints, and separation of offline model training from request-time inference.
- The machine-learning engineering pattern: source preprocessing, leakage-safe temporal features, chronological train/validation/test design, model-family benchmarks, model-backed sensitivity, risk thresholds, PCA/DBSCAN, and automated tests.
- The existing presentation component filenames `Hero.tsx`, `Footer.tsx` and `SignalTransition.tsx`; their visible copy and labels were retagged for India and the currently verified model.
- Useful model report, data provenance and deployment workflows, adapted to the verified India source rather than discarded.

## Modified

- Product identity, title, tagline, labels, accessible descriptions, system discovery, city/mode/operator selectors and station-centric results now use **India Transit Crowd AI** and **PREDICT THE CROWD. PLAN THE JOURNEY.**
- The former single-family data contract became a normalized system/city/mode/operator/entity/time/count/source record. An explicit family registry carries entity semantics, timezone, measure and artifact path.
- The BMRCL adapter verifies a pinned upstream file and its checksum, parses source local time, preserves reported zeros and leaves missing station-hours absent. Shared features and service methods accept the registered family timezone.
- Route-specific prediction, route history and route-profile screens became station/system-aware equivalents. Stale station fetches are discarded when the selected system changes; unsupported systems show data-unavailable notices instead of retaining a prior result.
- Deployment environment variables, Docker copies, runtime dependencies, API examples, tests and docs point to the Bengaluru family artifact and normalized observed source.
- Candidate system/source descriptions now distinguish network schedules from observed passenger demand and disclose access/license uncertainty.

## Removed or retired

- Old MTA/New York bus dataset extracts, route-level sample files, metadata, model artifacts and route analytics are not part of the India product or India metrics.
- Old route-view components and route-behaviour clustering names were retired; the active implementations are station/system aware (`StationSection`, `StationAnalyticsSection`, `ml/clustering/entity_behaviour.py`).
- The old MTA-specific setup instructions, data claims, API examples, benchmark claims and viva text were replaced. No earlier data rows, metrics, station/network identities or predictions were carried into India claims.
- The old model artifact at the generic models root was removed; the active artifact is isolated at `backend/models/bengaluru-namma-metro/`.

## Added

- Pinned, byte-verified BMRCL/Namma Metro hourly station-boardings source archive, reproducible adapter/normalizer, ODbL-1.0 license text, attribution/share-alike notice, normalized records and source sidecar.
- India discovery catalog for selected bus and metro references, with prediction state and source-specific unavailable reasons. Delhi OTD / Delhi Transport Stack, Mumbai BEST/TMT/KDMT GTFS, PMPML, CMRL, MMRDA, Kochi and Hyderabad source research is documented; network/schedule sources are never used as passenger-count targets.
- Separate model-family registry and mode/operator-scoped artifact directory. Only BMRCL is registered and loaded today; additional systems need compatible observed counts, permission/licensing, a source adapter and their own evaluation.
- Tests for ingestion/schema/provenance, timezone handling, missing observations, feature leakage, thresholds, training/inference, unsupported systems and the India frontend workflow.
- A final handoff report and a clean India ZIP, separate from the earlier archive.

## Historical note

The retired first version focused on a New York bus-route demand use case. That scope is preserved here only to explain the migration; its dataset, metrics, model and unsupported product claims have been removed from the active India documentation and release archive. The current model does not inherit, validate or extrapolate any result from that earlier scope.
