# Runtime health and rehearsal

## Contents
- Runtime health (phase 2)
- Controlled simulation (phase 8)
- Evidence to record
- Failure handling

## Runtime health (phase 2)
Goal: show ovphysx works, separate from the scene's contents.
- Use the library's bundled sample scene via `basic-workflow`, not the target. A scene with no movable bodies must not make a healthy runtime look broken, nor the reverse.
- Order: register the codeless PhysX schemas with ovstage before the first population call; populate (prefer the ALL domain mask for arbitrary content, since PHYSICS alone can drop colliders under native instances); advance the write floor and wait; `attach_ovstage` at that ordinal; `step_sync`; then release in order (bindings, detach, stage, destroy PhysX).
- Do not re-drain the initial read ordinal. Later stage edits use apply changes, advance write floor, then `update_from_ovstage`.
- If the project imports ovrtx too, import it before ovphysx.
- Verify any API name in the installed version before using it; do not assume methods exist.
- Record library version, outcome, and error text.

## Controlled simulation (phase 8)
Run only when explicitly authorized. Fix and record before starting:
- Initial conditions per body (pose, velocities), timestep (fixed), duration or step count, and gravity and units from the governing PhysicsScene.
- Attach the composed stage once. Read state through the session read API (`ovphysx-output-read`) and write only through the session write API (`ovphysx-session-write`) if initial state must be set. Use persistent bindings only when maintaining existing code.
- While running, physics owns the transforms of simulated bodies. Do not write those transforms from elsewhere; renderers and viewers consume physics output.
- Confirm runtime state advances (step count and elapsed time increase by the planned amounts).
- Check every pose read is finite (no NaN or inf) and comes from the runtime, not from authored values or a client.
- Evaluate task events and outcome criteria from the acceptance criteria (for example contact, containment, settle within tolerance), using numbers supplied by the user.
- Release bindings and tear down in the order above, also on failure.

## Evidence to record
- Controlled inputs: initial conditions, timestep, duration, scene mapping.
- Step count, elapsed simulated time, per-body pose samples (start, end, and at events), finite check result.
- Each outcome criterion with measured value, threshold, and pass or fail.
- Optional rendered frames, labelled supporting only.
- Teardown result.

## Failure handling
Report the first failing step with its error. Do not retry with altered parameters or loosen criteria silently; ask. A failed or skipped phase is reported as such in the persistent report.
