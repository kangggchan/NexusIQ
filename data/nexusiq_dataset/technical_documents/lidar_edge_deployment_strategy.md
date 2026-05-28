# LiDAR Edge Deployment Strategy

This note captures how the LiDAR team actually handles edge rollouts. The official story is that deployments proceed from Orin to Xavier with replay checks in between. The practical story is messier: the team uses canaries, hand-checked smoke packs, rollback notes, and a lot of judgment informed by prior incidents.

## Deployment Targets

- jetson-orin-dev-01 is the preferred first landing spot for new optimization experiments because it tolerates performance variance better and gives cleaner profiling output.
- jetson-xavier-edge-02 is the reality check. It surfaces regressions earlier, especially around queueing, allocator churn, and reload-heavy workflows.
- ops-vm-01 stores deployment breadcrumbs and supporting telemetry for later reconstruction.

## Nominal Rollout Sequence

1. Merge feature branch to main only after the commit history is tied to the relevant Jira thread.
2. Build prototype artifact tagged with the short commit hash and experiment label.
3. Deploy edge-inference-service first if TensorRT behavior changed, otherwise deploy the smallest surface needed for the experiment.
4. Run a replay clip pack on Orin and collect allocator counters, p95 latency, and deployment event breadcrumbs.
5. Promote to Xavier only if replay behavior survives both a fresh start and at least one representative restart path.
6. Record the rollout outcome even when the result is 'usable but still sketchy' because those soft failures are often the key to later incident reconstruction.

## Rollback Triggers

- p95 inference latency rises materially after an engine reload even if single-run benchmarks still look good.
- GPU free memory does not recover after replay session reset or after a supposedly harmless artifact reload.
- tracking-service age exceeds the demo threshold in dense scenes and the telemetry window suggests stateful degradation rather than a one-off spike.
- Deployment notes do not explain the observed behavior well enough to justify leaving the change in place.

## Lessons From Recent Rollouts

- INC-001 forced the team to admit that a fast INT8 path on paper can still be operationally worse if reload behavior is unstable.
- INC-013 reinforced the decision to keep Xavier canaries narrow and explicit about restart context.
- Multiple rollout notes now mention whether replay packs included repeated engine reloads, because that detail was missing from several early regressions.

## Operational Checks During A Rollout

- Verify /v1/profile/memory before and after replay loop execution.
- Capture telemetry-service deployment event plus the replay session identifier.
- Compare Orin and Xavier callback timing instead of trusting only throughput numbers.
- If rollback becomes likely, preserve both the active artifact and the prior stable artifact for trace comparison.

## What This Strategy Is Not

This is not a mature production deployment pipeline. It is a controlled engineering rollout process designed for a small team that needs realistic operational history more than ceremony. That means humans still make judgment calls, and the notes they leave are part of the system of record.

For investigation demos, that is a feature rather than a flaw. The ambiguity in the rollout narrative is what makes the dataset useful for root-cause analysis workflows.

## Service Inventory Snapshot

The following service snapshot is included so lidar edge deployment strategy can be read without cross-referencing the architecture overview every few paragraphs. This mirrors how internal docs usually accrete operational context over time.

- edge-inference-service: owner Diego Alvarez; dependencies lidar-ingestion-service, telemetry-service; key interfaces POST /v1/engine/reload, POST /v1/infer.
- object-detection-service: owner Aisha Khan; dependencies lidar-ingestion-service, edge-inference-service; key interfaces POST /v1/detections/run, ROS2 /lidar/detections.
- tracking-service: owner Minh Tran; dependencies object-detection-service, telemetry-service; key interfaces ROS2 /lidar/tracks, POST /v1/tracks/reset.
- telemetry-service: owner Sofia Petrov; dependencies none; key interfaces POST /v1/events, GET /v1/deployments/{service}.

## Incident And Ticket Traceability

These references are intentionally redundant. Engineers frequently land in a document from search or a graph traversal and need the nearby breadcrumbs to understand which operational threads matter.

- INC-001: LiDAR inference latency spike after INT8 rollout.
- INC-013: Xavier canary rollback after inference regression in demo branch.
- INC-018: Telemetry burst amplifies track lag on old Xavier image.
- LID-106 remains a live reference thread for this area.
- LID-121 remains a live reference thread for this area.
- LID-125 remains a live reference thread for this area.
- LID-131 remains a live reference thread for this area.

## Recommended Investigation Workflow

When behavior in this area regresses, the team has learned to follow a repeatable workflow instead of debating the most visible symptom first.

1. Confirm exact artifact, target rig, and restart context before interpreting rollout success.
2. Compare allocator and latency counters before and after replay rather than after startup only.
3. If symptoms appear downstream in tracking, reconstruct the inference and telemetry timeline before rolling back blindly.
4. Capture rollback evidence immediately, including whether recovery required additional restart steps.

## Open Technical Debt

- Canary criteria remain partly human and are therefore only as good as the notes captured during rollout.
- Xavier and Orin still expose different operational weaknesses, which complicates promotion rules.
- Rollbacks are routine enough that rollback metadata is part of the normal deployment story, not an exception.

## Questions Still Open

- Can Xavier gating be made stricter without slowing the team too much?
- Which rollout checks should become automated versus stay manually reviewed?
- How much replay coverage is enough before a demo-facing deployment is considered acceptable?
