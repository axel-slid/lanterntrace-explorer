# Release usability review 1

Public dialogue export from a local Codex session. Only user-visible user/assistant messages are included.
Hidden instructions, internal reasoning, environment metadata, tool calls, and tool output are intentionally excluded.

## Codex

I’m using the PDF skill for page-level visual verification and the computer-use skill for the packaged macOS behavior. I’ll audit from a clean clone and public release assets, not the working tree.

## Codex

The public tag, release assets, and two current CI runs all resolve to the requested commit. I’m now checking whether the downloadable binary actually matches the repository’s claims and whether a clean rebuild reproduces the scientific artifacts.

## Codex

Score: 9.2/10 — accepted for real-world use as a retrospective public research prototype.

Evidence:

- Public tag and release resolve to commit `6094e82`; both current GitHub CI runs pass.
- Clean-clone `research/reproduce.sh` completed successfully: 11 tests passed, all locked inputs verified, scientific tables regenerated without drift, and the PDF reproduced byte-identically.
- Frozen 2024–2025 coefficients are genuinely reused; prior reported cells are excluded from targets. Cook et al. (2021) is implemented as a fixed published-kernel transfer.
- Scientific claims are appropriately restrained: physics does not beat the covariate hazard, temporal replay is post-hoc rather than independent validation, and interpolation is explicitly labeled modeled evidence.
- The released app is polished and usable. I verified observations, frozen rankings, top-5% comparison, Frozen→Scenario transition, five simultaneous diffusion contours, smooth boundaries, forecast-off default/settings toggle, visible timeline, and working packaged paper link.
- Idle Electron, renderer, and GPU processes all settled to `0.0%` CPU.
- The 11-page paper is visually clean, legible, well structured, and has eight useful figures: `/tmp/lanterntrace-final-audit.5F2iQz/release/lanterntrace-frontier-forecasting.pdf`.

No blocker to ≥9 acceptance. Remaining concrete issues preventing production-grade status:

- The macOS build is development-signed but not notarized, so Gatekeeper rejects normal launch without an override.
- Independent prospective or structured-survey validation is still absent, correctly disclosed.
- `DATA_LICENSE.md` says the binary excludes the occurrence snapshot, while the released ASAR includes `generated/observations.js`; this documentation contradiction should be corrected.
