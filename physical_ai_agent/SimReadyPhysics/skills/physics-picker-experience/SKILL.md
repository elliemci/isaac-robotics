---
name: physics-picker-experience
description: Plan or build a physics-aware picker that lets a user grab and drag a simulated rigid body in a streamed viewport, with ovstream carrying mouse input, ovrtx resolving the hit, ovphysx applying forces, and ovphysx remaining the only motion authority. Never writes a transform for the picked body, rejects static, kinematic and protected geometry, and hands motion back to ovphysx on release. Use when asked to drag, grab, throw or interactively push a simulated object, or to add a physics picker or mouse-driven physics interaction to an OpenUSD scene. Do not use for selection outlines or highlight styling, camera orbit or pan, generic UI or frontend work, picking with no physics, or transform gizmos that author xformOp values.
---

# Physics Picker Experience

Extends `prepare-physics-rehearsal`: reuse its fixed rules (source hashing, never guess, approval before repair, layer ownership, revalidation, phase authorization, kept-distinct evidence). Add no library capability and do not modify a live application. Scene names, paths, counts and numbers from project history are examples only.

## Picker rules (a user brief may add, never weaken)

1. **No transform writes.** Never write `xformOp:transform`, `omni:xform`, position, orientation or a pose for the picked body, by any path. The host's existing physics-to-render handoff is the only transform writer.
2. **Force-based grab.** ovphysx has no native picker or pick constraint. Apply a damped spring through the session write API (`force` or `wrench`) toward the cursor target. Re-write it every step because it is cleared each step. Verify the installed version exposes these before planning on them.
3. **Explicit rejection.** Reject any hit that is not an eligible dynamic body (static, kinematic, simulation-disabled, protected, unmapped, or outside the approved set) and report the reason to the client. Never grab it.
4. **Release returns authority.** On button up, disconnect, pause or eligibility loss, drop the grab state and stop all picker writes in that step. Nothing else may keep steering the body.
5. **Physics owns motion** while running. Rendered frames are supporting evidence only.

## Pipeline to design

1. Input: ovstream `on_input` delivers MOVE and BUTTON mouse events (there is no separate drag or release event: drag is MOVE while pressed, release is BUTTON up). Queue them to the render thread.
2. Hit and validation: resolve the pointer ray to a hit with ovphysx `raycast` (authoritative), cross-check with the ovrtx pick hit, map to a prim path, and check eligibility from the validated body roles. Confirm units before converting any hit position.
3. Physics: write bounded spring-damper force at the grab point each step; keep the grab point in the body's local frame.
4. Feedback: ovrtx renders the updated world; ovstream sends frames and a status message (GRABBED, REJECTED with reason, RELEASED).

Details, event states and force law: [references/picker-pipeline.md](references/picker-pipeline.md).

## Stages

Stop at each gate and report.

1. **Diagnose.** Prove ovphysx health on the library's bundled sample; confirm raycast and force write exist in the installed version; confirm the input path delivers events. Execute nothing on the target.
2. **Validate.** Read-only: units, up axis, body roles, mass and inertia, collider coverage, governing PhysicsScene, which bodies are eligible and which are protected. Ask for the scene/body mapping if none or several.
3. **Authorize.** Present eligible set, force and speed limits, input mapping (the left button may already orbit the camera), and findings. Wait for explicit approval.
4. **Repair.** Approved findings only, to new correctly owned outputs. Sources untouched.
5. **Revalidate.** Same validator, target, profile and version; keep before and after evidence.
6. **Assemble.** Record picker configuration (eligible set, gains, caps, input mapping) in an application-owned layer or config. No physics opinions in presentation layers.
7. **Simulate.** Only when authorized. Scripted press, drag, release with fixed initial conditions, timestep and duration; exercise one accepted and one rejected pick.
8. **Prove.** Persistent report: force log, finite server-authoritative poses, rejection cases with reasons, post-release run showing free motion with zero picker writes, a transform-write audit for the picked body, source hashes unchanged, what was not run.

## Plan-only requests

Ask for missing targets, profile, units, axes, body roles, PhysicsScene mapping, input mapping, force limits and acceptance criteria instead of guessing. Propose owned outputs and the revalidation step, define runtime evidence, and execute nothing.
