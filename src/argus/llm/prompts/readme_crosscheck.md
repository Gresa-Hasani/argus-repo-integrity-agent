# Step: README versus implementation

Determine whether the README's technical claims are consistent with the repository evidence.

Each `readme_claim` evidence item contains the sentences that mention a technology, the supporting evidence found, and a deterministic status (VERIFIED, PARTIALLY_VERIFIED, NOT_VERIFIED).

Guidance:
- Read the mention in context before judging. A technology named as an alternative, a future plan, a comparison or a negation ("we do not use Redis") is not a claim: say so and do not raise a finding.
- NOT_VERIFIED means the detector found no supporting evidence, not that the claim is false. Raise README_MISMATCH (LOW or MEDIUM) only when the README clearly presents the technology as part of the implementation.
- Use "contradicted" only when the packet shows evidence against the claim (for example the README says automated tests exist and the structure evidence shows zero test files).
- Also compare claims about CI/CD and tests against the CI and structure evidence in the packet.
- A minimal README is a documentation weakness (LOW), not an integrity issue.
- Numeric model-quality claims are handed to the ML evaluator. Do not assess them.
