# Prototype Infrastructure Setup

The infrastructure in this workspace is intentionally realistic for a fast-moving startup: small, functional, and slightly uneven. It supports meaningful debugging and graph-based investigation, but it still relies on engineers remembering to leave good breadcrumbs.

## Shared Components

- telemetry-timeseries database for LiDAR runtime metrics and rollout breadcrumbs.
- model-registry for PointPillars artifacts and experiment tracking.
- calibration-state store for active camera profile metadata and runtime activation state.
- diagnostics-sqlite for prototype ADAS session summaries and anomaly correlation.

## Message Paths

- ROS2 topics for LiDAR ingestion, detections, and track output.
- NATS events for telemetry and diagnostics summaries.
- Shared-memory IPC for camera frames and lane model exchange on the ADAS side.
- CAN steer.command.v2 for controller output on the prototype rig.

## Deployment Targets

- jetson-orin-dev-01 and jetson-xavier-edge-02 for LiDAR prototype edge validation.
- adas-ecu-rig-01 and adas-ecu-rig-02 for controller and lane integration work.
- ops-vm-01 for aggregation of deployment and telemetry breadcrumbs.

## Operational Reality

This environment is not meant to impersonate a mature enterprise platform. It is a believable engineering environment where the system mostly works, the ownership model is clear, and the documentation is helpful but incomplete.

That incompleteness matters. The dataset is more useful for investigation because deployment records, telemetry counters, meeting notes, and Slack threads each reveal only part of the story.

## Why The Setup Works For Graph Investigation

- Service boundaries are explicit.
- Deployment state and runtime metrics are linked to commits and tickets.
- Human discussion artifacts preserve uncertainty, disagreement, and operational shortcuts.
- Incidents cross service boundaries without collapsing into a single obvious root-cause sentence in one file.

## Service Inventory Snapshot

The following service snapshot is included so prototype infrastructure setup can be read without cross-referencing the architecture overview every few paragraphs. This mirrors how internal docs usually accrete operational context over time.

- lidar-ingestion-service: owner Minh Tran; dependencies none; key interfaces POST /v1/frames/import, ROS2 /lidar/points_raw.
- object-detection-service: owner Aisha Khan; dependencies lidar-ingestion-service, edge-inference-service; key interfaces POST /v1/detections/run, ROS2 /lidar/detections.
- tracking-service: owner Minh Tran; dependencies object-detection-service, telemetry-service; key interfaces ROS2 /lidar/tracks, POST /v1/tracks/reset.
- edge-inference-service: owner Diego Alvarez; dependencies lidar-ingestion-service, telemetry-service; key interfaces POST /v1/engine/reload, POST /v1/infer.
- telemetry-service: owner Sofia Petrov; dependencies none; key interfaces POST /v1/events, GET /v1/deployments/{service}.
- camera-ingestion-service: owner Haruka Sato; dependencies calibration-service; key interfaces POST /v1/replay/frame, IPC /camera/front_center.
- lane-detection-service: owner Priya Raman; dependencies camera-ingestion-service, calibration-service; key interfaces POST /v1/lane/infer, IPC /lane/model.
- steering-control-service: owner Lucas Moreau; dependencies camera-ingestion-service, lane-detection-service; key interfaces POST /v1/controller/reset, CAN steer.command.v2.
- calibration-service: owner Nora Ibrahim; dependencies none; key interfaces POST /v1/calibration/upload, GET /v1/calibration/active.
- diagnostics-service: owner Haruka Sato; dependencies lane-detection-service, steering-control-service, calibration-service; key interfaces POST /v1/diag/events, GET /v1/diag/session/{session_id}.

## Incident And Ticket Traceability

These references are intentionally redundant. Engineers frequently land in a document from search or a graph traversal and need the nearby breadcrumbs to understand which operational threads matter.

- INC-002: Tracking delay during dense replay with telemetry enabled.
- INC-003: Lane offset after warm ECU restart on calibration branch.
- INC-009: Camera frame gap spike during verbose diagnostics capture.
- INC-015: Telemetry deployment metadata missing on rollback events.
- LID-122 remains a live reference thread for this area.
- LID-132 remains a live reference thread for this area.
- ADAS-211 remains a live reference thread for this area.
- ADAS-228 remains a live reference thread for this area.

## Recommended Investigation Workflow

When behavior in this area regresses, the team has learned to follow a repeatable workflow instead of debating the most visible symptom first.

1. Identify which data source should be treated as the time anchor for the incident under review.
2. Walk message paths from ingestion to downstream consumer and note where clocks or caches can diverge.
3. Use deployment records to bound the investigation window before reading human discussion artifacts.
4. Only then aggregate cross-source evidence into a graph or incident timeline.

## Open Technical Debt

- Infrastructure is coherent enough for investigation, but still relies on operators remembering contextual details.
- Metadata normalization remains incomplete across telemetry, diagnostics, and deployment logs.
- Some message paths are better instrumented than others, which biases how quickly teams notice problems.

## Questions Still Open

- Where should shared metadata contracts live?
- Which message paths need better back-pressure or queue visibility?
- How much ops discipline is currently encoded only in team habit?
