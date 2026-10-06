---
name: prepare-physics-rehearsal
description: Take an OpenUSD scene from read-only physics diagnosis to a reviewable, physics-ready rehearsal. Routes the agent through ovphysx runtime health, explicit-target SimReady validation with structured evidence, approval-gated repair, correctly owned layer assembly, revalidation, and authorized fixed-step ovphysx simulation with a persistent report. Use when asked to prepare an OpenUSD scene for a physics rehearsal, make a scene physics-ready or SimReady, validate a scene for simulation, repair approved findings safely, or prove a result with ovphysx. Do not use for viewer styling, camera or lighting tweaks, generic UI or frontend work, render-only tasks, or USD authoring with no physics intent.
---

# Prepare Physics Rehearsal

Orchestrate existing ovphysx, SimReady validation, and Omniverse Realtime Viewer guidance. Add no library capability, and never rebuild or modify a live application (for example a running portal). Treat any scene, path, count or dimension in project history (Old Attic, Memory Cube, C-9) as an example only, never a rule.

## Fixed rules (a user brief may add to these, never weaken them)

1. **Source integrity.** Record SHA-256 of every source layer before work and compare after. Never edit a source in place. Writes go only to new paths.
2. **Never guess.** If a target, profile and version, units, up axis, body role, governing PhysicsScene, or acceptance criterion is missing, ask. Do not infer it from names or defaults.
3. **Approval.** Repair requires a current report for the same target and profile/version, and explicit user approval naming the findings. A stale or mismatched report is not a basis for repair.
4. **Ownership.** Write each output only to the layer that owns it:
   - reusable asset conformance: a new asset output
   - scene-specific physics: a scene-owned layer
   - presentation overlays (outlines, highlights, colors): an application-owned layer only
5. **Revalidate.** After repair, rerun the same validator on the same target and profile/version, and keep before and after evidence side by side.
6. **Phase authorization.** Simulation runs only when the user has explicitly authorized that phase. Rendered frames are supporting evidence only. While physics runs, physics owns transforms.
7. **Keep distinct** in every report: library capability, 3D domain judgment, asset-level SimReady evidence, composed-scene runtime evidence, application orchestration, protected source content.

## Phases

Stop at each gate and report before continuing. Detail for each phase is in the references.

1. **Intake.** Collect the items in rule 2 plus authorized outputs, runtime budget (timestep, duration), and acceptance criteria. See [references/intake-and-evidence.md](references/intake-and-evidence.md). Hash sources.
2. **Diagnose.** Prove ovphysx runtime health independently of the scene, using the library's own bundled sample, so a healthy runtime is established even if the scene has no movable bodies. Follow the installed `basic-workflow` skill (schema registration, `open_usd`, seal, `attach_ovstage`, `step_sync`, ordered teardown). See [references/runtime-rehearsal.md](references/runtime-rehearsal.md).
3. **Validate.** Run the validator read-only against explicitly named targets and profiles. No authoring, no stepping. Preserve exact Requirement IDs and structured before evidence. Check units, up axis, body roles, task-relevant collision coverage, and functional clearance or negative space from the acceptance criteria. Identify the PhysicsScene that governs the rehearsal; if none or several exist, ask for the intended scene/body mapping.
4. **Authorize.** Present findings as a reviewable list (Requirement ID, evidence, proposed change, owning layer). Wait for explicit approval. Findings that are not repairable, or outside approval, stay open.
5. **Repair.** Apply only approved findings, to new outputs by ownership (rule 4). No change to protected sources.
6. **Revalidate.** Rule 5. Compare before/after per Requirement ID. Report anything unresolved or newly introduced.
7. **Assemble.** Compose the physics-ready stage non-destructively: physics layer stronger than the authored scene, application overlays in their own layer above. Read back the stage contract (units, up axis, roles, collision coverage, clearance) from the composed result, not from the inputs.
8. **Simulate.** Only if authorized. Require controlled initial conditions, timestep and duration; confirm runtime state advances, poses are finite and read from the server-authoritative runtime, and task events and outcome criteria are evaluated. Release bindings cleanly.
9. **Prove.** Write the persistent report (schema in [references/intake-and-evidence.md](references/intake-and-evidence.md)): hashes unchanged, before/after evidence, contract readback, runtime evidence, open issues, and what was not run. Never claim success without it.

## Routing

- ovphysx runtime and state: installed ovphysx skills `basic-workflow`, `ovphysx-usd-authoring`, `ovphysx-session-write`, `ovphysx-output-read`. Locate them in the active ovphysx install and confirm they exist. `tensor-bindings-*` is deprecated; use only to maintain existing code.
- Validation and fixing: the project's SimReady validator and guarded fixer, if present. If none is found, ask rather than inventing rules.
- Viewer picking and outlines: the ovrtx `picking-selection` skill, for presentation layers only.

## Plan-only requests

When asked only to plan, produce phases 1–9 for the stated scene with missing items listed as questions, owned output paths proposed, the revalidation step, and the runtime evidence definition. Execute nothing: no validation, authoring, live applications, or simulation.
