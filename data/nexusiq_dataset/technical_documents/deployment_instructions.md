# Deployment Instructions

These instructions are intentionally written for prototype engineering work, not safety certification or production release. They are meant to preserve enough consistency that investigation after a bad rollout is possible without pretending that the team has already built a mature release process.

## LiDAR Prototype Rollout

1. Build artifact from the linked main commit and retain the short commit hash in deployment notes.
2. Deploy edge-inference-service first when TensorRT or engine lifecycle behavior changed.
3. Run the replay smoke pack and compare current metrics against the latest telemetry baseline, not against memory.
4. Check /v1/profile/memory before and after replay if the branch changed quantization, engine reload behavior, or allocator handling.
5. Hold Xavier rollout if allocator counters, tracking age, or replay stability start drifting in ways the notes cannot explain.

## ADAS Prototype Rollout

1. Build the ECU package and publish diagnostics schema with the same tag.
2. Upload calibration bundle, then force cache flush if the rig was already warm or if a previous session used a different profile.
3. Enable timing-profile-b only in controlled replay sessions and record that choice explicitly.
4. Capture diagnostics session summary with both the active package version and calibration checksum before higher-speed replay.
5. Roll back immediately if steering jitter appears above 70 km/h or if timestamp evidence becomes internally inconsistent.

## Failure Handling Expectations

- Always preserve the deployment id, source commit id, and target rig when opening an incident or Jira follow-up.
- If a rollback occurs, note whether the symptom improved immediately or only after additional restart steps.
- Do not summarize a rollout as stable unless it survived both replay and restart context that actually matches the intended use case.

## Examples Worth Reading

- INC-001 and INC-013 for LiDAR rollback examples tied to edge inference changes.
- INC-003 and INC-017 for calibration-related mitigations where the surface symptom was downstream.
- INC-004 and INC-016 for controller rollback patterns and timing-profile caution.

## Service Inventory Snapshot

The following service snapshot is included so deployment instructions can be read without cross-referencing the architecture overview every few paragraphs. This mirrors how internal docs usually accrete operational context over time.

- edge-inference-service: owner Diego Alvarez; dependencies lidar-ingestion-service, telemetry-service; key interfaces POST /v1/engine/reload, POST /v1/infer.
- telemetry-service: owner Sofia Petrov; dependencies none; key interfaces POST /v1/events, GET /v1/deployments/{service}.
- camera-ingestion-service: owner Haruka Sato; dependencies calibration-service; key interfaces POST /v1/replay/frame, IPC /camera/front_center.
- steering-control-service: owner Lucas Moreau; dependencies camera-ingestion-service, lane-detection-service; key interfaces POST /v1/controller/reset, CAN steer.command.v2.
- diagnostics-service: owner Haruka Sato; dependencies lane-detection-service, steering-control-service, calibration-service; key interfaces POST /v1/diag/events, GET /v1/diag/session/{session_id}.
- calibration-service: owner Nora Ibrahim; dependencies none; key interfaces POST /v1/calibration/upload, GET /v1/calibration/active.

## Incident And Ticket Traceability

These references are intentionally redundant. Engineers frequently land in a document from search or a graph traversal and need the nearby breadcrumbs to understand which operational threads matter.

- INC-001: LiDAR inference latency spike after INT8 rollout.
- INC-003: Lane offset after warm ECU restart on calibration branch.
- INC-004: Steering jitter on timing-profile-b during highway replay.
- INC-016: Prototype ECU package rollback after controller jitter regression.
- LID-106 remains a live reference thread for this area.
- LID-127 remains a live reference thread for this area.
- ADAS-206 remains a live reference thread for this area.
- ADAS-227 remains a live reference thread for this area.

## Recommended Investigation Workflow

When behavior in this area regresses, the team has learned to follow a repeatable workflow instead of debating the most visible symptom first.

1. Identify the exact scope of the rollout and what kind of behavior changed: model, timing, cache, or deployment metadata.
2. Run the smallest credible smoke pack that matches the risk of the change.
3. Capture evidence before and after any mitigation or rollback.
4. Update Jira and deployment logs while the context is fresh instead of reconstructing the story later.

## Open Technical Debt

- The instructions describe disciplined prototype work, not mature release management.
- Several steps remain easy to skip when engineers are rushing to validate a theory.
- Rollback evidence quality is still inconsistent across teams.

## Questions Still Open

- Which instructions should fail closed if skipped?
- How much of the rollout context can be attached automatically to deployments?
- What evidence threshold should block demo-facing deployment promotion?
