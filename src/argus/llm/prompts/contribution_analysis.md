# Step: contribution analysis — who contributed what, raw versus meaningful

Interpret the per-contributor metrics. Separate RAW activity (commits, raw additions) from MEANINGFUL engineering activity (the meaningful source estimate, tests, components touched).

Guidance:
- Do not rank contributors as better or worse. Do not treat commit count or LOC as quality.
- A contributor whose raw additions are mostly lockfiles, generated, vendored or data files has a raw LOC figure that overstates original work: say so with the measured numbers (LOC_INFLATION). This is usually an artefact of who ran the scaffold, not manipulation.
- A highly uneven distribution is an observation. Consider role split, a single integrator, or pairing on one machine before treating it as CONTRIBUTION_INTEGRITY.
- Contributors of kind `ai_tool`, `bot` or `platform` are not team members; do not assess them as people.
- Estimates derived from path classification are estimates. Do not present them as exact.
