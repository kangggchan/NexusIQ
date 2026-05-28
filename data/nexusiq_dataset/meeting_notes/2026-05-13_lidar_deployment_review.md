# LiDAR Deployment Review - 2026-05-13

Focus: rollback patterns after INC-013 and how narrow Xavier canaries should remain.

## Notes

- Team agreed that Orin-only canaries are acceptable if they unblock engine profiling.
- Xavier remains the better early warning signal for unstable optimization changes.
- Deployment notes must mention whether engine reloads happened during the replay pack.

## Tone In The Room

- Nobody argued against moving fast; the disagreement was about what counts as enough evidence to move the canary forward.
- The group was visibly tired of postmortems that reconstruct restart context from partial Slack fragments.

## Action Items

- Keep Xavier canaries explicit about reload and replay context.
- Make rollback notes name the exact artifact and target rig without relying on memory.
