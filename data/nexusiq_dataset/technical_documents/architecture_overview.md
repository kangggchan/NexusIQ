# NovaDrive AI Architecture Overview

This document is intended to read like an internal architecture note, not a polished marketing summary. The company has two active programs, both in the uncomfortable middle ground where the fundamentals work but the operational edges still move every week.

The LiDAR project is late-stage from a model and pipeline perspective, but still fragile at the edge deployment layer. The ADAS lane keeping project is earlier and more argumentative: algorithms are still in comparison mode, control behavior is not yet stable at higher speed, and integration assumptions change more often than anyone wants to admit.

## Program Scope

NovaDrive AI is running two small, tightly staffed engineering efforts. The LiDAR Perception Team owns the 3D detection stack for autonomous vehicle prototyping, while the ADAS Vision Team owns the lane keeping stack for a camera-based ECU deployment path.

Neither program should be described as production-ready. Both have enough real operational history to support investigation workflows, but they also carry the mess that comes from fast iteration, partial rollback strategies, and a lot of debugging happening in Slack and Jira rather than in clean design documents.

- LiDAR stack emphasis: TensorRT optimization, Jetson deployment behavior, GPU memory efficiency, replay-driven debugging.
- ADAS stack emphasis: lane detector experimentation, calibration lifecycle, controller timing, ECU packaging preparation.
- Shared platform reality: telemetry, deployment logging, and diagnostics are good enough for engineering analysis but not yet governed like formal production systems.

## Team Ownership And Boundaries

Service ownership is intentionally direct because the company is small. Every service maps to a real owner, and team leads still review most risky changes even when the implementation detail sits with an individual specialist.

Cross-team work usually appears when a downstream symptom is misleading. For example, lane offset can look like a model issue while actually depending on calibration cache lifecycle, and tracking delay can look like tracker logic while actually being shaped by ROS2 behavior and telemetry load.

- LiDAR Perception Team services: lidar-ingestion-service, object-detection-service, tracking-service, edge-inference-service, telemetry-service.
- ADAS Vision Team services: camera-ingestion-service, lane-detection-service, steering-control-service, calibration-service, diagnostics-service.
- Team leads act as integration choke points, especially before demo-facing deployments or rollback decisions.

## LiDAR Runtime Flow

- The core detection path works reliably enough to support active optimization work.
- The unstable parts are mostly around repeated engine reloads, allocator behavior, and timing interactions during replay-heavy sessions.
- Telemetry is operationally important because the most expensive LiDAR failures are timeline problems rather than obvious single-service crashes.

1. lidar-ingestion-service receives raw point clouds and normalizes them for replay and live edge testing.
2. object-detection-service wraps PointPillars preprocessing, postprocessing, and decode behavior around the inference path.
3. edge-inference-service owns the TensorRT engine lifecycle, CUDA stream handling, quantized artifact loading, and device-level profiling hooks.
4. tracking-service converts bursty detections into short-horizon tracks used by visualization and planning mocks.
5. telemetry-service aggregates deployment events, allocator counters, replay metrics, and breadcrumbs that later become critical during incident reconstruction.

## ADAS Runtime Flow

- The ADAS stack is less mature than the LiDAR stack and changes shape more often.
- Algorithm debates are still active, which means architecture notes cannot pretend the final decomposition is settled.
- Several visible controller issues are actually timing or calibration lifecycle issues in disguise.

1. camera-ingestion-service captures frames and emits them through the front camera IPC path.
2. calibration-service exposes active intrinsic and extrinsic data and mediates profile activation across the prototype environment.
3. lane-detection-service runs experimental lane extraction paths and publishes lane models with confidence output.
4. steering-control-service consumes lane geometry and transforms it into CAN steering commands with tunable smoothing and damping logic.
5. diagnostics-service stores the context needed to compare replay sessions, controller jitter, and timing anomalies.

## Dependency Map And Integration Assumptions

The service graph is intentionally small, but the important detail is not just who depends on whom. The important detail is where state and timing can drift across boundaries. That is where the incidents keep clustering.

When the system behaves badly, the surface symptom frequently appears one hop away from the initiating mistake. That is why a GraphRAG demo should traverse commits, deployments, Slack threads, and notes instead of trusting one artifact type.

- object-detection-service depends on lidar-ingestion-service, edge-inference-service.
- tracking-service depends on object-detection-service, telemetry-service.
- edge-inference-service depends on lidar-ingestion-service, telemetry-service.
- camera-ingestion-service depends on calibration-service.
- lane-detection-service depends on camera-ingestion-service, calibration-service.
- steering-control-service depends on camera-ingestion-service, lane-detection-service.
- diagnostics-service depends on lane-detection-service, steering-control-service, calibration-service.

## Current Operational Pressure Points

- LiDAR: repeated TensorRT engine reloads can distort allocator state and make latency look worse after otherwise reasonable optimization changes.
- LiDAR: ROS2 message latency spikes are not uniformly visible across devices, which is why Orin and Xavier runs diverge in frustrating ways.
- ADAS: calibration lifecycle after warm restart is still too implicit and too easy to misread from a single checksum.
- ADAS: steering jitter above highway-like replay speeds depends on timing alignment, controller gains, and diagnostics overhead together, not separately.
- Both projects: deployment breadcrumbs are essential because restart state and rollout order matter more than raw code diff size.

## Cross-Document Investigation Threads

Several incidents deliberately leave only partial clues in any single source. The goal is to make investigation require synthesis instead of simple keyword matching.

- INC-001 and INC-013 both intersect edge-inference-service rollouts and reinforce the need to distinguish benchmark wins from deployment-safe behavior.
- INC-003 and INC-017 both point back to calibration-service cache handling even though the visible symptom appears in lane behavior.
- INC-002 and INC-018 both involve tracking-service timing under telemetry pressure, which means the tracker owns the symptom but not the whole problem.

## Near-Term Architecture Direction

The practical architecture direction for the next month is not radical redesign. It is better operational visibility, tighter state boundaries after restart and reload, and fewer hidden assumptions inside deployment and replay tooling.

If the teams can make lifecycle behavior explicit, a lot of the apparently mysterious runtime bugs become ordinary engineering work instead of week-long investigations.

## Service Inventory Snapshot

The following service snapshot is included so architecture overview can be read without cross-referencing the architecture overview every few paragraphs. This mirrors how internal docs usually accrete operational context over time.

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

- INC-001: LiDAR inference latency spike after INT8 rollout.
- INC-002: Tracking delay during dense replay with telemetry enabled.
- INC-003: Lane offset after warm ECU restart on calibration branch.
- INC-004: Steering jitter on timing-profile-b during highway replay.
- INC-018: Telemetry burst amplifies track lag on old Xavier image.
- LID-103 remains a live reference thread for this area.
- LID-117 remains a live reference thread for this area.
- ADAS-203 remains a live reference thread for this area.
- ADAS-207 remains a live reference thread for this area.
- ADAS-214 remains a live reference thread for this area.

## Recommended Investigation Workflow

When behavior in this area regresses, the team has learned to follow a repeatable workflow instead of debating the most visible symptom first.

1. Start with deployment and restart context before analyzing the visible symptom.
2. Walk the service dependency chain one hop upstream and one hop downstream from the affected surface.
3. Check related Slack and meeting-note context for hints about hidden assumptions or recent experiments.
4. Only after the operational timeline is coherent should code diffs be treated as primary evidence.

## Open Technical Debt

- Restart and reload state are still under-documented relative to how often they shape incidents.
- Telemetry and diagnostics metadata evolve quickly and can drift from service assumptions unless owners keep notes current.
- Cross-team symptoms still arrive faster than cross-team design updates.

## Questions Still Open

- Which lifecycle boundaries need explicit APIs rather than convention-driven scripts?
- How much metadata normalization is enough before it slows down the teams unacceptably?
- Which failures are device-specific versus architecture-specific?
