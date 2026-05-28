# ADAS Architecture Review - 2026-03-19

Attendees: Haruka Sato, Priya Raman, Lucas Moreau, Nora Ibrahim, Ethan Walker

Reference branch merge discussed: caf5b69f for merge: ADAS-201 Compare gradient and spline lane detectors on wet-road data.

## Discussion

- Lane detection is still in active algorithm comparison mode. Nobody argued that one path is dominant across glare, curves, and wet-road replay.
- Calibration-service needs a cleaner boundary between uploaded profile metadata and runtime cache state.
- Steering-control-service should not absorb timestamp ambiguity silently because replay hides timing issues that show up later in controller behavior.

## Notable Quotes

- Priya: if the lane model looks worse after warm restart, I want calibration ruled out before we touch the detector again.
- Lucas: smoothing can make the graphs calmer while the controller truth gets murkier.
- Nora: checksum is not the same thing as fresh runtime state and we keep acting like it is.

## Decisions

- Keep spline and gradient detectors alive for another sprint.
- Add calibration checksum and extrinsic-age visibility to diagnostics summaries.
- Avoid calling the ECU package stable until high-speed jitter data is repeatable.
