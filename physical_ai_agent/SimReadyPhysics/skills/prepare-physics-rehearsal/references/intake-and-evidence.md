# Intake and evidence

## Contents
- Intake checklist
- Output ownership
- Requirement evidence record
- Persistent report

## Intake checklist
Ask for anything not supplied. Do not fill gaps from filenames or past scenes.
- Targets: exact layer or prim paths to validate, and which are protected sources.
- Profile name and version for the validator, and the validator entry point.
- Units (metersPerUnit, mass and time units) and up axis the rehearsal must use.
- Body roles per prim: dynamic, kinematic, static, trigger or none, with the moving and containing parties named.
- PhysicsScene: which prim governs, gravity and units it should carry. If none or several candidates exist, ask for the scene/body mapping.
- Acceptance criteria: collision coverage the task needs, any clearance or negative space (opening, gap, fit) with its number and tolerance, outcome events.
- Authorized outputs and phases (repair, assemble, simulate), with output locations.
- Runtime budget: initial conditions, timestep, duration.
- Optional learner-authored brief: additive context only.

## Output ownership
| Content | Destination |
|---|---|
| Reusable asset conformance (collision, mass, material on the asset) | New asset output, versioned and reusable across scenes |
| Scene-specific physics (PhysicsScene, placement-specific bodies, ground, scene materials) | Scene-owned layer |
| Presentation overlays (outlines, highlights) | Application-owned layer, no physics opinions |
| Sources | Untouched |

Strength order for composition: scene-owned physics over the authored scene; application overlay as a separate layer. Never put physics in an overlay or presentation in a physics layer.

## Requirement evidence record
Keep one record per finding, before and after, both from the same validator, target and profile/version:
- requirement_id (exact string from the validator; never rename or merge)
- target, profile, profile_version, validator_version
- status, structured evidence fields as emitted, measured values and units
- repairable flag, approved flag, owning layer for the fix

## Persistent report
Write to a reviewable file (JSON preferred) containing:
- request, authorized phases, and approvals with the findings they cover
- source hashes before and after, and a drift result
- before and after evidence per requirement_id, and the revalidation verdict
- composed-stage contract readback: units, up axis, body roles, governing PhysicsScene, collision coverage, clearance
- runtime evidence (see runtime-rehearsal.md) or an explicit "not run"
- open issues, and what was deliberately not executed
- separate sections for library behavior, domain judgment, asset evidence, scene runtime evidence, orchestration
