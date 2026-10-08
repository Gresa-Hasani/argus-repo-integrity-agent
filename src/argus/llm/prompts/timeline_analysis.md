# Step: timeline analysis — how the project developed over time

Relate project start, commit cadence, branches, merges, pull requests, the introduction of tests/CI, large code drops and final-window activity.

Guidance:
- Interpret branch usage relative to team size and duration. Committing directly to the default branch in a short or solo project is normal. Absence of pull requests is not a problem by itself.
- A large share of meaningful source arriving in the final window, or in one commit, is an observation with several legitimate explanations (migration from another repository, squashed history, branch merge, offline development, scaffold). Use the commit details in the packet to see which explanation the evidence supports. If none can be confirmed, it stays unresolved: raise TIMELINE_ANOMALY with `requires_manual_review: true`.
- Commits after a configured deadline are a factual observation; whether the rules allow them is for a human to decide.
- Timestamps are client-supplied. Divergent author/commit dates usually mean rebase or amend.
- If pull-request or workflow-run data is marked unavailable, say it is unverifiable. Do not assume it was fine.
- Use categories TIMELINE_ANOMALY, BRANCH_WORKFLOW or CI_CD.
- For an anomaly marked `"material": true` your explanation is advisory: it is attached for the human reviewer and does not remove the review requirement.
