# Release usability review 2

Public dialogue export from a local Codex session. Only user-visible user/assistant messages are included.
Hidden instructions, internal reasoning, environment metadata, tool calls, and tool output are intentionally excluded.

## Codex

I’m using the PDF and computer-use workflows for this audit because the score depends on both the paper’s rendered evidence and the packaged app’s actual behavior. I’ll evaluate the public release at the stated commit without editing it.

## Codex

The release is public, its tag resolves to the requested commit, both assets are attached with recorded SHA-256 digests, and two clean CI runs on that commit passed. I’m now checking whether the scientific claims and packaged interactions match that release evidence rather than relying on the README.

## Codex

Score: 8.9/10.

One blocker to ≥9: after enabling scenarios and advancing into 2027, switching to Frozen Evaluation leaves the bottom timeline showing “2027 Sep · prospective step” and the 2026–2030 forecast band while the map and panel show frozen 2025 results. Controls disable correctly, but the conflicting temporal states weaken a key scientific safeguard. Reset or hide the timeline when entering frozen mode.

Everything else is strong:

- Public v0.2.3 release and assets match commit `6094e82`; both current CI runs pass.
- Release ZIP/PDF hashes match local verified artifacts.
- Eleven scientific tests pass; clean CI reconstructs the locked analysis and detects result drift.
- Frozen 2024–2025 replay is real and honestly described as post-hoc temporal separation, not prospective validation.
- Cook et al. (2021) is a legitimate fixed literature-kernel transfer, explicitly not misrepresented as a full replication.
- Sparse-report interpolation is clearly labeled modeled continuity, not observed occupancy or confidence.
- Packaged app is polished, responsive, idle at negligible CPU, development-signed, and contains the correct paper.
- Frozen evaluation, eight comparators, model selection, allocation overlays, scenario opt-in, monthly stepping/playback, settings safeguards, and bundled PDF link all worked.
- The 11-page paper is cleanly rendered, story-led, contains eight useful figures, reports negative/non-dominant findings honestly, and makes limitations unusually explicit: `$HOME/Downloads/lanterntrace-explorer/output/pdf/lanterntrace-frontier-forecasting.pdf`

Proportional deductions, not blockers: no notarization, untagged PDF, no permanent DOI, incomplete funding/COI declarations, reserved licensing, and no preregistered or independent-survey validation. For the explicitly claimed retrospective research-prototype/preprint scope, fixing the cross-mode timeline inconsistency would bring this to approximately 9.2/10.

## Codex

I’m reusing the computer-use workflow because this follow-up is narrowly about the live cross-mode interaction. I’ll verify the exact public commit, CI, release hashes, and only the previously failing timeline transition.

## Codex

The live v0.2.4 transition now behaves correctly: switching from actively playing April 2027 to Frozen Evaluation immediately stops playback, resets to December 2025, removes the forecast band and 2026–2030 labels, and leaves only the disabled evidence timeline. I’m waiting for the two public CI runs on the exact commit to finish before issuing the revised score.

## Codex

Final score: 9.2/10.

The sole blocker is fixed in v0.2.4:

- From active April 2027 scenario playback, switching to Frozen Evaluation stopped playback and reset the timeline to December 2025.
- The forecast band and 2026–2030 labels disappeared.
- Only the 2019–2025 evidence timeline remained, with controls disabled.
- The frozen panel, map, annotation, slider, and timeline now present one consistent temporal state.

Both public CI runs passed on exact commit `0c6219521bf2b7e717ece95a9d383118eb305c5b`. The public assets match the supplied hashes: PDF `f1cdefec…` and ZIP `49573209…`.

No remaining ≥9 blocker within the stated retrospective research-prototype/preprint scope.
