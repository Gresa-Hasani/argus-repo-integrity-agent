# Step: executive summary

Write the executive summary of the ARGUS report as JSON: {"executive_summary": "..."}.

Rules:
- 4 to 8 sentences of plain prose. No markdown, no lists.
- Use only facts and numbers present in the packet. Do not introduce any new number, name, date or claim.
- State the evaluation status exactly as given in `completion_status` and explain it using `status_reasons`.
- Mention the scale of the repository, the main healthy signals, the main weaknesses, and anything requiring manual review.
- `manual_review_required` is authoritative. If it is false, do not say or imply that manual review is needed.
- If there are evaluator errors or coverage gaps, say so plainly. Do not describe an incomplete or failed evaluation as clean.
- Neutral, factual tone. No accusations and no praise beyond what the evidence supports.
