# Step: authorship analysis — identities, author vs committer, co-authorship

Interpret the identity map, author/committer differences and the co-authorship matrix.

Guidance:
- Author, committer and co-author are different roles. Author != committer is normally explained by GitHub web merges, rebases, cherry-picks or bots (`committer_kind` tells you which).
- Identities are merged only on repository evidence. `possibly_same_person_as` is a hint for a human reviewer, not a fact: raise it as an INFO note if it would change how contribution counts are read.
- `Co-authored-by` is legitimate. Co-authorship alone is NEVER proof of cheating. Only raise COAUTHOR_INTEGRITY when the measured pattern is unusual (for example: almost no independent commits but many co-authored appearances, a co-author on nearly every commit, trailers concentrated on trivial commits or appearing only at the very end) AND say which legitimate explanations fit.
- When a co-authorship anomaly is material and the packet cannot distinguish pair programming from attribution padding, raise a finding with `requires_manual_review: true`. Do not resolve it by assumption and do not accuse.
- AI-tool co-authors (kind `ai_tool`) are attribution of tool usage, not a co-authorship integrity issue.
- For an anomaly marked `"material": true` your explanation is advisory: it is attached for the human reviewer and does not remove the review requirement.
