# Step: commit analysis — message quality, granularity, inflation indicators

Assess whether the commit history is understandable and traceable.

Look at: share of low-information messages and the sampled messages, repeated messages, commit classification mix, large commits, tiny/empty/whitespace-only commits, rapid bursts of trivial commits, reverts.

Guidance:
- Conventional Commits are not required. Judge traceability, not style.
- Poor commit messages are an engineering weakness (COMMIT_INTEGRITY, LOW or MEDIUM). They are never misconduct by themselves.
- A large commit is not suspicious by itself; an initial scaffold or a dependency lockfile explains many of them. Check `non_original_additions` and `is_root_commit` before commenting.
- Trivial or empty commits are only a COMMIT_INFLATION concern when they form a pattern that materially changes commit counts. State the measured share. Never infer intent from the pattern alone.
