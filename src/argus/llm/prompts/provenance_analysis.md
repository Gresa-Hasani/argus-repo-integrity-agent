# Step: provenance analysis — similarity evidence and origin of the code

Interpret the measured similarity comparisons and any large code drops.

Guidance:
- Similarity numbers are measured by a deterministic token-shingle comparison over meaningful source only. Never restate a different number.
- The configured threshold is in the packet. An estimate at or above it requires manual review; it is NOT a plagiarism verdict. A deterministic rule already raises that flag (see `existing_findings`) — add interpretation, do not duplicate it.
- Explain what was compared, which files overlap most, and whether the overlap is likely meaningful: framework boilerplate, official examples, starter templates and declared forks or templates (`fork`, `parent`, `template` in repository metadata) are legitimate sources of similarity.
- Overlap cannot tell you who copied whom.
- If no comparison was performed, say that provenance is unverified. Do not conclude that the code is original.
- Use categories CODE_PROVENANCE or SIMILARITY.
