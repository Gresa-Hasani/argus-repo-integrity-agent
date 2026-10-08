# Step: integrity synthesis — cross-evidence reasoning

You are given every anomaly detected so far, every finding already raised, and the key metrics. Combine independent signals. No single metric is sufficient.

Tasks:
1. Look for combinations that reinforce each other (for example: a very large late commit + one contributor with almost all LOC + a new contributor with no earlier history + similarity evidence). When several independent signals point the same way, raise ONE cross-evidence finding that cites all of them, with category CONTRIBUTION_INTEGRITY, CODE_PROVENANCE or TIMELINE_ANOMALY, and `requires_manual_review: true` if intent or provenance cannot be determined.
2. Look for combinations that explain each other benignly (for example: a large root commit whose additions are mostly lockfile/scaffold; uneven LOC in a solo project). Resolve those anomalies in `resolved_anomalies` with an explanation that names the evidence.
3. Do not repeat findings that already exist (listed under `existing_findings`). Only add what the combination adds.
4. Every anomaly in the packet is still open. Each one marked `"material": true` must be either resolved with an evidence-grounded explanation or cited by a finding. If you cannot tell, raise a finding citing it with `requires_manual_review: true`.

Write `summary` as the overall integrity assessment: distinguish raw activity from meaningful engineering activity, and state plainly what remains unresolved. Never state or imply misconduct; describe evidence and what needs review.
- For an anomaly marked `"material": true` your explanation is advisory: it is attached for the human reviewer and does not remove the review requirement.
