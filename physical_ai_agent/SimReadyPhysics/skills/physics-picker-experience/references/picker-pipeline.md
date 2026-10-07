# Picker pipeline

## Contents
- Guidance to read first
- Input state machine
- Hit resolution
- Force law
- Release and failure
- Status messages

## Guidance to read first
Confirm each exists in the active install before relying on it.
- `ovphysx-session-write` (force and wrench writes), `ovphysx-output-read` (state reads), `basic-workflow`: the installed ovphysx skills. `tensor-bindings-*` is deprecated.
- ovstream `callbacks-and-input` (file is named `SKILLS.md`): `on_input`, mouse event fields.
- ovrtx `picking-selection` and the viewer references `native-picking-selection`, `prim-transform-safety`, `viewer-input-routing`.

## Input state machine
IDLE -> GRABBED on left BUTTON down with an eligible hit -> DRAGGING on MOVE while held -> RELEASED on BUTTON up, disconnect, pause or eligibility loss -> IDLE. Coordinates are client pixels; use the absolute-coordinate width and height in the event to normalize. Callbacks run on SDK threads: queue, then process on the render thread. If the same button also orbits the camera, require a modifier or mode toggle and suppress orbit while grabbed.

## Hit resolution
- Build the ray from the pointer and the camera. Cast with ovphysx `raycast`; resolve returned body handles to prim paths with the scene-query path helper.
- Cross-check against the ovrtx pick hit for the same pixel. If they disagree, reject with a reason rather than choosing one.
- Eligible means dynamic, simulation enabled, in the approved set, not protected. Static and kinematic bodies are rejected explicitly.
- Units: the hit position unit and frame must be confirmed against the stage's metersPerUnit before use. Do not assume.

## Force law
- At press, store the grab point in the body's local frame and the drag plane (for example camera-facing through the hit).
- Each step: target = pointer ray intersected with the plane; force = stiffness * (target - grab point world) - damping * point velocity, with the magnitude capped (scale caps by mass and gravity; values are user-approved, not defaults).
- Write the force at the grab point (`wrench`) or at the centre of mass (`force`). Fill every entry of the write group before committing. Writes before the first step or warmup are refused.
- Re-write every step; forces clear each step. Never write position, orientation, pose or velocity state for the body.

## Release and failure
- On release clear the grab and write nothing further; the body then moves only under ovphysx. Optionally cap residual speed through the approved limit by stopping force, not by overwriting state.
- On any failed write or non-finite pose: release the grab, report the first failure, and do not retry with altered limits without asking.
- Keep teardown ordered per `basic-workflow`.

## Status messages
Send small JSON through `send_message` (limit 65535 bytes): state (GRABBED, DRAGGING, REJECTED, RELEASED), prim path, rejection reason, step count. The server's value is authoritative; the client only displays it.
