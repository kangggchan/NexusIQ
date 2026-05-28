# ADAS ECU Integration Prep

This document is the closest thing the ADAS team has to a real integration playbook. It is not a final validation document and should not be treated that way. Its purpose is to reduce avoidable setup variance while the architecture is still changing underneath the team.

## Services In Scope

- camera-ingestion-service for frame capture and timestamping.
- lane-detection-service for active lane model inference.
- steering-control-service for controller output and timing-profile management.
- diagnostics-service for run summaries and anomaly breadcrumbs.
- calibration-service because integration quality depends on active profile lifecycle more than the initial docs suggested.

## Prototype Deployment Checklist

1. Confirm ECU image version, diagnostics sampler mode, and intended timing profile.
2. Upload calibration bundle and verify GET /v1/calibration/active checksum plus the reported age of the active runtime state.
3. Restart camera-ingestion-service if the rig was warm rebooted or if the previous session used a different calibration profile.
4. Verify steering-control-service is using the intended timing profile and damping configuration before any higher-speed replay.
5. Capture diagnostics session summary before and after replay so controller and calibration changes can be compared later.

## Current Gaps

- Timing source differences are still being traced rather than fully documented.
- Calibration lifecycle remains under-documented for warm restart scenarios.
- Highway-like replay still depends on hand-checked controller limits and human judgment.
- Package notes can drift from diagnostics schema changes unless both are updated together.

## Recent Operational Notes

- ADAS-205 prepared ECU packaging for controller drops, but the packaging path still depends on good notes more than on a hardened pipeline.
- ADAS-214 added camera timing instrumentation work because controller symptoms were too easy to misread from coarse logs.
- ADAS-227 forced a rollback after jitter regression in a prototype package, which highlighted how much package context matters for later investigations.

## Investigation Bias To Avoid

The easiest mistake is to blame the lane detector for everything because lane behavior is what humans notice first. In practice, calibration state, timing alignment, and controller configuration can each distort the symptom enough to make a model change look guilty when it is not.

That is why the ADAS team keeps insisting on replay evidence with explicit setup notes. Without that, conversations loop around intuition instead of narrowing the actual failure surface.

## Service Inventory Snapshot

The following service snapshot is included so adas ecu integration prep can be read without cross-referencing the architecture overview every few paragraphs. This mirrors how internal docs usually accrete operational context over time.

- camera-ingestion-service: owner Haruka Sato; dependencies calibration-service; key interfaces POST /v1/replay/frame, IPC /camera/front_center.
- lane-detection-service: owner Priya Raman; dependencies camera-ingestion-service, calibration-service; key interfaces POST /v1/lane/infer, IPC /lane/model.
- steering-control-service: owner Lucas Moreau; dependencies camera-ingestion-service, lane-detection-service; key interfaces POST /v1/controller/reset, CAN steer.command.v2.
- calibration-service: owner Nora Ibrahim; dependencies none; key interfaces POST /v1/calibration/upload, GET /v1/calibration/active.
- diagnostics-service: owner Haruka Sato; dependencies lane-detection-service, steering-control-service, calibration-service; key interfaces POST /v1/diag/events, GET /v1/diag/session/{session_id}.

## Incident And Ticket Traceability

These references are intentionally redundant. Engineers frequently land in a document from search or a graph traversal and need the nearby breadcrumbs to understand which operational threads matter.

- INC-003: Lane offset after warm ECU restart on calibration branch.
- INC-004: Steering jitter on timing-profile-b during highway replay.
- INC-016: Prototype ECU package rollback after controller jitter regression.
- INC-017: Lane tests blocked by stale calibration cache after repeated uploads.
- ADAS-205 remains a live reference thread for this area.
- ADAS-214 remains a live reference thread for this area.
- ADAS-224 remains a live reference thread for this area.
- ADAS-227 remains a live reference thread for this area.

## Recommended Investigation Workflow

When behavior in this area regresses, the team has learned to follow a repeatable workflow instead of debating the most visible symptom first.

1. Capture package version, diagnostics schema, and active calibration state before replay.
2. Validate timestamp source alignment before interpreting steering symptoms.
3. If the rig was warm, flush or verify calibration runtime state explicitly rather than assuming the prior sequence handled it.
4. Preserve session summaries before rollback so the evidence is not erased by recovery actions.

## Open Technical Debt

- Warm-restart handling is still not explicit enough in the playbook.
- Package notes and diagnostics schema changes can drift apart under schedule pressure.
- The checklist still depends on human discipline for several critical steps.

## Questions Still Open

- Which setup steps should become automated guards?
- How much restart context needs to be persisted in the diagnostics summary?
- What is the minimum evidence bar for trying timing-profile-b again?
