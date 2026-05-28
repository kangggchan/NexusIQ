# Optimization Discussion - 2026-05-10

Cross-team discussion on benchmark quality versus operational quality.

## LiDAR Topics

- INT8 continues to outperform FP16 on Orin when the engine is loaded once and left alone.
- Repeated reload loops still make the system look less stable than the raw single-pass benchmarks suggest.
- Several engineers agreed that the current benchmark harness is better at measuring promise than at measuring deployment safety.

## ADAS Topics

- Controller smoothing experiments improved lane comfort on replay, but only at lower speed.
- Timing-profile-b remains suspect until sensor and controller clocks are reconciled.
- Calibration and controller threads keep colliding, which is a sign that the evidence boundary is still too fuzzy.

## Shared Observation

Benchmarks without deployment and restart context keep overstating maturity. The group agreed that a fast result is interesting, but a fast result that survives real operating context is what actually matters.
