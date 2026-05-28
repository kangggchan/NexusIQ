# LiDAR Sprint Review - 2026-03-05

Attendees: Minh Tran, Aisha Khan, Diego Alvarez, Sofia Petrov, Jonas Mueller

Reference merge in review packet: fb7eeec0 for merge: LID-101 Stabilize TensorRT INT8 edge inference path.

## Progress

- LID-101 INT8 edge inference path is functional on Orin and usable for the current replay pack.
- LID-104 postprocess copy reduction landed, but nobody wants to overclaim the win until regression coverage catches up.
- Replay harness improvements from LID-119 reduced setup time, which is already paying back during iteration.

## Discussion Notes

- Minh: the model path is no longer the scary part; deployment state is.
- Diego: the first clean benchmark after restart keeps making the branch look healthier than it really is.
- Sofia: if telemetry metadata keeps drifting, every retro becomes archaeology.
- Jonas: Xavier is still the better liar detector for unstable optimization work.

## Risks

- Engine reload path still lacks good allocator visibility.
- Tracking behavior is stable only on shorter replay clips.
- The team still has a habit of treating one clean Orin run as stronger evidence than it is.

## Follow-Up

- Diego to land allocator counters linked to LID-111.
- Jonas to keep Xavier deployment checklist narrow until rollback frequency drops.
- Aisha to capture a side-by-side note on FP16 versus INT8 behavior after restart, not only at startup.
