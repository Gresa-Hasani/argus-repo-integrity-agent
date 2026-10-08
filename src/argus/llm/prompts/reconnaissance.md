# Step: reconnaissance — repository structure and hygiene

Assess whether the repository's organisation and hygiene are coherent for its technology stack.

Look at: detected ecosystems, top-level layout, file categories, code composition (scc), `.gitignore`, environment files, dependency manifests, committed generated/vendored content.

Guidance:
- Judge the structure relative to the stack and size of the project. A small project does not need an elaborate layout.
- Missing optional files (LICENSE, tests, Docker) are INFO or LOW observations, not integrity concerns.
- Committed dependency directories, build output or real `.env` files are hygiene weaknesses. Deterministic rules already raise findings for those and for secret indicators (listed under `existing_findings`); do not restate them.
- Use categories REPOSITORY_HYGIENE or LOC_INFLATION. Do not comment on contributors or commit history here.
