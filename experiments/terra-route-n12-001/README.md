# Terra route 12-pair task suite

This directory publishes the reproducible inputs for the expanded Terra-worker/Sol-reviewer experiment.

## Contents

- `pilot-repo/`: baseline source and public tests for Tasks 03–12;
- `replacement-repo/`: baseline source and public tests for replacement Task 13;
- `definitions/`: frozen Mission Contracts, Work Orders, and model-identity records;
- `hidden/`: deferred hidden suites disclosed after experiment completion;
- `suite-manifest.json`: task metadata and content hashes;
- `run-schedule.json`: frozen randomized waves and the transparent Task 08 exclusion record;
- `prepare_suite.py` and `prepare_replacement.py`: deterministic fixture generators.

Tasks 01–02 are the previously published low/high bug-fix pilots in `evidence/labs/terra-route-model-only-001`. Tasks 03–07 and 09–13 form the ten new valid pairs. Task 08 is not part of the 12-pair inference because its hidden assertion contradicted the frozen Acceptance Spec; its reason remains recorded in the schedule.

Raw model transcripts, private working directories, credentials, and machine-specific runner paths are intentionally not published. The normalized hashed pair records and authoritative report are in [`evidence/labs/terra-route-n12-001/`](../../evidence/labs/terra-route-n12-001/).

The published fixture directories omit their original `.git` databases. To regenerate contracts against a new fixture commit, initialize and commit `pilot-repo/` and `replacement-repo/` first, then run the corresponding preparation script. The authoritative historical base hashes remain frozen in the published pair records.
