# Incident Postmortem - INC-003

Subject: lane offset after warm ECU restart on the calibration branch.

## Summary

Lane offset appeared after a warm ECU restart on the calibration branch. The first instinct in the room was to blame the lane model, but the deeper the team looked, the more the evidence pointed back toward calibration lifecycle behavior and stale runtime state after restart.

## Evidence Reviewed

- Jira: ADAS-203, ADAS-206, ADAS-224.
- Calibration upload logs and active profile checksums.
- Replay sessions before and after explicit cache flush.
- Controller and lane summaries to confirm the symptom was upstream of steering behavior.

## Discussion Notes

- Haruka pushed the team to stop treating a correct checksum as conclusive evidence of correct runtime state.
- Priya argued that the lane model was being over-accused because the visible symptom was lane offset rather than an obvious calibration error.
- Nora noted that the upload path was too forgiving and hid the fact that runtime state could remain stale across warm restart paths.
- Ethan pointed out that the rig procedure still mixed clean-boot and warm-boot assumptions in the same checklist, which made the evidence muddy.

## What We Learned

- A correct checksum does not guarantee the active runtime state is fresh.
- Warm restart paths still behave differently than cold boot setup.
- Lane detection symptoms can be downstream evidence rather than the origin.
- Cache lifecycle needs to be explicit in both docs and tooling or the team will keep relearning the same lesson.

## Next Steps

- Make cache flush a first-class step in the rig checklist.
- Separate metadata persistence from the runtime transform cache.
- Tag future replay summaries with restart context so comparisons are not based on guesswork.
