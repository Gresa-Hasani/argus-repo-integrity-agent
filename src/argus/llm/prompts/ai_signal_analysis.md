# Step: AI-assistance signals

Classify the strength of OBSERVABLE evidence of AI-assisted development and set `classification` to exactly one of: LOW, MODERATE, HIGH, INSUFFICIENT_EVIDENCE.

Guidance:
- Explicit attribution is direct evidence of tool usage: AI-tool identities as author/co-author, tool markers in commit messages, assistant configuration files (CLAUDE.md, AGENTS.md, .cursorrules, ...).
- Indirect indicators (large coherent code drops, comment ratio, placeholder markers) are weak and have many other causes. They can raise the classification by at most one level and never to HIGH on their own.
- You cannot determine that code is AI-generated from style. Never state or estimate a percentage of AI-generated code.
- AI assistance is not misconduct unless the evaluation rules in the packet prohibit or restrict it. Unless they do, report signals as an INFO finding with category AI_ASSISTANCE and `requires_manual_review: false`.
- With no explicit attribution and only weak indicators, use INSUFFICIENT_EVIDENCE or LOW and raise no finding.
