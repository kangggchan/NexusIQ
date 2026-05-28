# Platform Sync - 2026-04-01

Attendees: Sofia Petrov, Jonas Mueller, Ethan Walker, Nora Ibrahim, Minh Tran, Haruka Sato

## Notes

- Telemetry and diagnostics schemas keep drifting with service changes.
- Rollback metadata was incomplete in one LiDAR canary and made post-run debugging slower than necessary.
- ADAS upload scripts still assume a clean restart path, which no longer matches how the rigs are actually used.

## Discussion Texture

- The group agreed that incomplete metadata is now a material debugging tax, not just documentation sloppiness.
- There was mild disagreement about whether to force schema normalization immediately or tolerate more drift while features are still moving quickly.
- Consensus landed on doing the smallest normalization that improves reconstruction without slowing the teams to a crawl.

## Action Items

- Sofia to normalize deployment metadata shape.
- Ethan to capture ECU package version and diagnostics schema together.
- Nora to document the cache flush expectation more explicitly.
