# LiDAR Service API Notes

This document expands the lightweight API sketch into something closer to the internal notes engineers actually use while debugging replay sessions and edge rollouts. It intentionally includes operational caveats, because several LiDAR incidents only make sense if API behavior is read together with deployment and memory-state assumptions.

## object-detection-service Interface

object-detection-service is the service most engineers touch when experimenting with model behavior, but it is not the lowest-level performance boundary. It sits between raw frame handling and the TensorRT execution path, which means it often receives blame for issues that begin in inference lifecycle handling.

- POST /v1/detections/run: replay-oriented entry point that accepts frame_id, replay_session_id, calibration_profile, and experiment flags; returns decoded 3D boxes, confidence distribution, and stage timing split between preprocessing, inference, and decode.
- GET /metrics: exposes p50 and p95 latency, decoder copy count, postprocess queue depth, and stale metric warnings after service reload.
- Operational note: this service should be treated as stateless for inference semantics, but its observability path can still lag after reload if metrics are not reinitialized correctly.

## edge-inference-service Interface

edge-inference-service is the true operational risk center for the LiDAR stack. It manages TensorRT engine loading, CUDA stream reuse, calibration artifact activation, and allocator visibility. A clean benchmark on a fresh process does not guarantee clean behavior after reload-heavy validation workflows.

- POST /v1/infer: low-latency gRPC or internal call path invoked by object-detection-service; returns inference tensor output plus lightweight device counters.
- POST /v1/engine/reload: loads a new engine after quantization or calibration changes; callers should record why the reload happened because repeated reloads are materially correlated with unstable sessions.
- GET /v1/profile/memory: exposes free GPU memory, allocator pool size, buffer reuse count, and engine reload count; this endpoint became much more important after LID-103 and LID-121.
- Operational note: repeated reload loops on the same Jetson should not be treated as equivalent to a fresh startup even if the artifact hash is unchanged.

## tracking-service Interface

tracking-service is intentionally simple from an API perspective, but operationally it is where upstream timing mistakes become human-visible. When tracks age out or lag, engineers often start here because the symptom is obvious even though the cause may live elsewhere.

- POST /v1/tracks/reset: clears tracker state between replay sessions; should be called on short-clip validation loops to prevent stale IDs from contaminating measurements.
- ROS2 /lidar/tracks: publishes tracked objects for visualization, planning mocks, and internal debug tools.
- GET /healthz: reports callback backlog, stale track count, and most recent telemetry-linked queue observations.

## Telemetry Coupling

telemetry-service is not a pure side system. It participates in how engineers understand the LiDAR runtime, and in some cases it shapes the failure surface indirectly by changing load and callback timing. That is why telemetry behavior must be considered part of the operational API contract.

- POST /v1/events should always receive deployment_id, replay_session_id, and service_version where available.
- GET /v1/deployments/{service} is frequently used during incident reconstruction and should not omit rollback metadata.
- If metrics lag after restart, engineers should trust raw deployment logs before trusting the dashboard layer.

## Expected Failure Patterns

- LID-103: p95 inference spike investigation tied to engine reload behavior and allocator visibility gaps.
- LID-107: tracking delay when telemetry exporter is enabled, especially on dense replay runs and older Xavier images.
- LID-121: watchdog-restart and engine reload behavior are not operationally equivalent to clean startup inference.
- LID-127: demo-branch rollout looked acceptable in build notes but still forced rollback once replay context changed.

## Usage Guidance For Investigation Workflows

For GraphRAG and investigation use cases, API references should be linked to deployments, commits, and note artifacts rather than treated as standalone truth. The right question is usually not only 'what does the endpoint do' but also 'what operational state makes this endpoint trustworthy or misleading'.

That framing is especially important for LiDAR because edge behavior is path-dependent. The system often looks stable until a replay session, reload sequence, or deployment history makes a previously hidden weakness visible.

## Service Inventory Snapshot

The following service snapshot is included so lidar api notes can be read without cross-referencing the architecture overview every few paragraphs. This mirrors how internal docs usually accrete operational context over time.

- object-detection-service: owner Aisha Khan; dependencies lidar-ingestion-service, edge-inference-service; key interfaces POST /v1/detections/run, ROS2 /lidar/detections.
- edge-inference-service: owner Diego Alvarez; dependencies lidar-ingestion-service, telemetry-service; key interfaces POST /v1/engine/reload, POST /v1/infer.
- tracking-service: owner Minh Tran; dependencies object-detection-service, telemetry-service; key interfaces ROS2 /lidar/tracks, POST /v1/tracks/reset.
- telemetry-service: owner Sofia Petrov; dependencies none; key interfaces POST /v1/events, GET /v1/deployments/{service}.

## Incident And Ticket Traceability

These references are intentionally redundant. Engineers frequently land in a document from search or a graph traversal and need the nearby breadcrumbs to understand which operational threads matter.

- INC-001: LiDAR inference latency spike after INT8 rollout.
- INC-002: Tracking delay during dense replay with telemetry enabled.
- INC-007: Engine cache refresh skipped after deployment smoke test.
- INC-013: Xavier canary rollback after inference regression in demo branch.
- LID-103 remains a live reference thread for this area.
- LID-107 remains a live reference thread for this area.
- LID-111 remains a live reference thread for this area.
- LID-121 remains a live reference thread for this area.
- LID-127 remains a live reference thread for this area.

## Recommended Investigation Workflow

When behavior in this area regresses, the team has learned to follow a repeatable workflow instead of debating the most visible symptom first.

1. Check whether the caller path involved replay, restart, or engine reload before trusting performance counters.
2. Compare endpoint semantics with the deployment notes for the exact source commit.
3. Use telemetry breadcrumbs to decide whether the API response can be interpreted as steady-state behavior or transient state.
4. Correlate tracker symptoms with upstream inference and telemetry timing rather than treating tracking as the only locus of failure.

## Open Technical Debt

- The API docs still lag behind the operational meaning of restart, reload, and replay state.
- Metrics and health endpoints are not always sufficient without deployment metadata attached nearby.
- Some clients still assume fresh-start equivalence after reload, which is false in practice.

## Questions Still Open

- Should reload behavior become a first-class part of the API contract rather than an operational caveat?
- Which counters belong in the stable API surface versus experimental debug-only endpoints?
- How much client behavior depends on undocumented timing assumptions?
