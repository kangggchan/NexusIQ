# ADAS Controller Review - 2026-05-15

Focus: steering jitter seen in INC-004 and INC-016.

## Notes

- Controller smoothing and timestamp choice are too intertwined right now.
- Diagnostics still needs both sensor-time and monotonic-time views for the same session.
- Highway replay is useful, but it masks some real-world pacing effects.

## Discussion Texture

- Lucas was clear that pinning the older timing profile helps the symptom but does not explain it.
- Haruka pushed for better evidence discipline before another gain change goes out.
- Ethan warned that package notes and diagnostics schema changes are drifting apart too easily.

## Action Items

- Lucas to keep timing profile changes behind explicit flags.
- Ethan to keep prototype package notes aligned with diagnostics changes.
- Haruka to require a clearer before-and-after summary when controller tuning claims improvement.
