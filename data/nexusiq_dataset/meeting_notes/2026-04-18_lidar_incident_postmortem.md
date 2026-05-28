# Incident Postmortem - INC-002

Subject: delayed object tracking during dense replay with telemetry enabled.

## Summary

Dense replay runs showed delayed object tracking while telemetry exporter was enabled. The visible symptom was stale tracks, but the evidence trail crossed tracker code, ROS2 timing, telemetry load, and device differences between Orin and Xavier.

## Evidence Reviewed

- Jira: LID-107, LID-116, LID-117.
- Deployment window around tracking-service changes.
- Replay traces from Xavier and comparison runs on Orin.
- Slack thread fragments where telemetry timing was initially treated as a side note.

## What The Team Argued About

- Whether the tracker itself was too slow versus whether the subscriber backlog was the real surface.
- How much telemetry load was acceptable during replay without poisoning the measurement.
- Whether Orin results were misleading the team into dismissing Xavier-specific symptoms too early.

## What We Learned

- Tracking delay is not isolated to tracker code.
- Telemetry burst behavior can change the shape of the symptom.
- QoS choices that feel harmless on Orin become more obvious on Xavier.

## Next Steps

- Keep telemetry batching improvements narrow.
- Collect side-by-side callback traces before another Xavier demo branch rollout.
- Require replay identifiers in future incident notes so dense-scene failures can be compared more cleanly.
