# LiDAR Optimization Notes

These notes capture the current optimization phase for the LiDAR project. The important context is that the team is not fighting for raw benchmark wins alone. They are trying to make edge behavior predictable enough that a good performance result survives deployment, restart, replay, and rollback pressure.

## Active Optimization Themes

- TensorRT optimization and quantized engine packaging.
- Inference latency reduction with explicit attention to p95, not just median latency.
- GPU memory efficiency on Jetson devices under replay-heavy validation workflows.
- ROS2 communication stability between ingestion, detection, and tracking services.

## Working Observations

- INT8 gains are real on Orin, but those gains are easier to trust on fresh startup than after repeated engine reloads.
- Decoder copy reduction matters, but allocator churn and state retention matter more once calibration swaps enter the picture.
- Tracking delay sometimes appears first even when the upstream issue is allocator pressure or telemetry-driven callback contention.
- A single replay pack is not enough evidence for declaring an optimization safe.

## Hypotheses The Team Keeps Revisiting

- Reload-heavy sessions fragment or retain GPU buffers more than the team originally assumed.
- The same TensorRT change can look fine on Orin and still be fragile on Xavier due to a different balance of compute headroom and callback timing.
- Telemetry and ROS2 timing interact in ways that make downstream symptoms look like tracker problems.

## Pinned Jira Work

- LID-102 profile Jetson memory pools during repeated engine reload.
- LID-111 add allocator counters to /v1/profile/memory.
- LID-117 measure telemetry burst impact on ROS2 callback timing.
- LID-124 compare FP16 and INT8 latency on Orin build 0.9.x.

## Notes Engineers Keep Repeating In Reviews

Do not confuse a fast branch with a stable branch. The team has enough history now to know that edge instability often shows up only after deployment and replay conditions are involved.

Also, do not accept 'works after restart' as the same thing as 'works across restarts'. That distinction matters for the current state of edge-inference-service more than almost any other service in the system.

## Service Inventory Snapshot

The following service snapshot is included so lidar optimization notes can be read without cross-referencing the architecture overview every few paragraphs. This mirrors how internal docs usually accrete operational context over time.

- edge-inference-service: owner Diego Alvarez; dependencies lidar-ingestion-service, telemetry-service; key interfaces POST /v1/engine/reload, POST /v1/infer.
- object-detection-service: owner Aisha Khan; dependencies lidar-ingestion-service, edge-inference-service; key interfaces POST /v1/detections/run, ROS2 /lidar/detections.
- tracking-service: owner Minh Tran; dependencies object-detection-service, telemetry-service; key interfaces ROS2 /lidar/tracks, POST /v1/tracks/reset.

## Incident And Ticket Traceability

These references are intentionally redundant. Engineers frequently land in a document from search or a graph traversal and need the nearby breadcrumbs to understand which operational threads matter.

- INC-001: LiDAR inference latency spike after INT8 rollout.
- INC-002: Tracking delay during dense replay with telemetry enabled.
- INC-007: Engine cache refresh skipped after deployment smoke test.
- INC-018: Telemetry burst amplifies track lag on old Xavier image.
- LID-102 remains a live reference thread for this area.
- LID-111 remains a live reference thread for this area.
- LID-117 remains a live reference thread for this area.
- LID-124 remains a live reference thread for this area.

## Recommended Investigation Workflow

When behavior in this area regresses, the team has learned to follow a repeatable workflow instead of debating the most visible symptom first.

1. Reproduce the optimization on both Orin and Xavier with the same replay identifiers.
2. Measure both startup and post-reload behavior.
3. Inspect downstream tracking and telemetry symptoms before concluding the change is localized.
4. Preserve enough notes that a later postmortem can reconstruct the run without private memory.

## Open Technical Debt

- Optimization evidence is still too benchmark-heavy relative to deployment-heavy reality.
- Allocator and QoS behavior produce second-order effects that are easy to miss in isolated tests.
- The team still lacks a single report that combines replay, reload, and deployment context cleanly.

## Questions Still Open

- Which optimization wins are robust enough to survive realistic deployment churn?
- Where should memory instrumentation live long term?
- How much of the observed variance is true model behavior versus lifecycle noise?
