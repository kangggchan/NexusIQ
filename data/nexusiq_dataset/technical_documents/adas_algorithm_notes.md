# ADAS Lane Algorithm Notes

The ADAS lane stack is still in a mid-stage algorithm development phase. There is enough structure to discuss services and APIs, but not enough certainty to pretend that the current model path is final. These notes deliberately preserve that uncertainty.

## Current Experimental Paths

- Gradient-heavy edge detector for high-contrast highway scenes.
- Spline-based lane fitting for curved exits and smoother lane geometry.
- Hybrid mask smoothing path for shadow transitions and glare-heavy segments.

## Current Constraints

- Prototype ECU compute budget remains tight and rules out several heavier experiments.
- Camera calibration issues can shift the apparent lane center and make algorithm quality look worse than it is.
- Steering evaluation depends on timestamps that are not yet fully reconciled across ingestion, control, and diagnostics.

## Observed Behavior In Practice

The team has not converged on one detector because each path fails differently. The gradient path can behave well in crisp scenes but get brittle under harsh lighting changes. The spline-heavy path can produce visually better geometry while also introducing enough latency or instability to hurt downstream confidence.

This is why ADAS discussion threads look more argumentative than the LiDAR ones. The uncertainty is real, and several experiments remain plausibly useful depending on which weakness the team decides matters most in the next milestone.

## Open Questions

- Is spline fitting worth the additional latency on the current ECU generation?
- Should calibration cache flush become mandatory after every upload until lifecycle behavior is simpler?
- Can diagnostics sampling remain enabled during higher-speed replay without contaminating the symptom?
- How much controller smoothing hides a perception defect versus legitimately improving comfort?

## Related Jira Work

- ADAS-201 detector comparison on wet-road data.
- ADAS-203 lane center drift after warm restart.
- ADAS-207 steering oscillation with timing-profile-b enabled.
- ADAS-214 camera timing instrumentation for ECU integration.

## Service Inventory Snapshot

The following service snapshot is included so adas algorithm notes can be read without cross-referencing the architecture overview every few paragraphs. This mirrors how internal docs usually accrete operational context over time.

- camera-ingestion-service: owner Haruka Sato; dependencies calibration-service; key interfaces POST /v1/replay/frame, IPC /camera/front_center.
- lane-detection-service: owner Priya Raman; dependencies camera-ingestion-service, calibration-service; key interfaces POST /v1/lane/infer, IPC /lane/model.
- calibration-service: owner Nora Ibrahim; dependencies none; key interfaces POST /v1/calibration/upload, GET /v1/calibration/active.
- diagnostics-service: owner Haruka Sato; dependencies lane-detection-service, steering-control-service, calibration-service; key interfaces POST /v1/diag/events, GET /v1/diag/session/{session_id}.

## Incident And Ticket Traceability

These references are intentionally redundant. Engineers frequently land in a document from search or a graph traversal and need the nearby breadcrumbs to understand which operational threads matter.

- INC-003: Lane offset after warm ECU restart on calibration branch.
- INC-009: Camera frame gap spike during verbose diagnostics capture.
- INC-014: Road replay glare causes lane confidence collapse.
- INC-017: Lane tests blocked by stale calibration cache after repeated uploads.
- ADAS-201 remains a live reference thread for this area.
- ADAS-203 remains a live reference thread for this area.
- ADAS-211 remains a live reference thread for this area.
- ADAS-215 remains a live reference thread for this area.

## Recommended Investigation Workflow

When behavior in this area regresses, the team has learned to follow a repeatable workflow instead of debating the most visible symptom first.

1. Confirm calibration and restart context before comparing detector variants.
2. Check diagnostics output for timestamp anomalies before blaming perception confidence alone.
3. Run the same clip on the competing detector branches before judging one-off performance complaints.
4. Record which shadows, glare, or curvature cases were present so later comparisons stay grounded.

## Open Technical Debt

- Algorithm quality is still too easy to conflate with calibration and timing quality.
- Experiment tracking exists, but interpretation still depends heavily on discussion context.
- The team lacks a settled definition of what counts as good-enough stability for the next milestone.

## Questions Still Open

- Which algorithm path degrades most gracefully when the calibration path is slightly wrong?
- How much controller behavior should influence detector selection at this stage?
- Can experiment toggles be simplified without losing useful ambiguity?
