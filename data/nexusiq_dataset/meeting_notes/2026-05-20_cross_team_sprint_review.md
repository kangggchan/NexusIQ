# Cross-Team Sprint Review - 2026-05-20

Attendees: both team leads, service owners, and DevOps support from both programs.

## Highlights

- LiDAR core pipeline is operational, but edge deployment remains the unstable surface.
- Lane keeping algorithms are improving, but calibration and timing work still dominate incident response.

## Shared Risks

- Runtime state after reload or restart remains under-documented.
- Prototype deployment logs are essential for GraphRAG-style investigations because no single source tells the whole story.
- Teams are still one bad week away from repeating a failure simply because setup context did not get captured cleanly.

## Next Sprint

- LiDAR: continue allocator and QoS work.
- ADAS: isolate calibration cache lifecycle and steering timestamp boundaries.
- Platform: improve metadata consistency without pretending the environment is already production-grade.
