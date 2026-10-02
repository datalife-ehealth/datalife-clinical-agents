# Contributing to DataLife Clinical Agents

The organization-wide
[contribution rules](https://github.com/datalife-ehealth/.github/blob/main/CONTRIBUTING.md)
apply here. Agent changes also need evidence that they are bounded, reproducible,
and reviewable.

## Proposal checklist

Before implementing a new workflow, document:

- the intended user and the decision the agent may assist with;
- inputs, outputs, retention, and every external tool or model provider;
- actions the agent is explicitly forbidden to take;
- the human-review point and safe failure behavior;
- prompt-injection, data-exfiltration, and excessive-agency threats; and
- offline metrics, baselines, fixtures, and acceptance thresholds.

Use synthetic or explicitly licensed de-identified data only. Never paste patient
records, API keys, model transcripts containing sensitive data, or hidden
chain-of-thought into the repository.

## Pull requests

Keep one workflow or safety improvement per pull request. Link its issue or RFC,
include deterministic tests, pin evaluation inputs, and report both successful and
failed cases. New tools must be deny-by-default, typed, narrowly scoped, and covered
by authorization tests. Approval from the repository steward is required.
