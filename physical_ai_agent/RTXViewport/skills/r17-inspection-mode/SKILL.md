---
name: r17-inspection-mode
description: Plan or add robot-inspection controls (target-focused camera, semantic-segmentation view, optional Lidar evidence panel) to an existing browser-streamed ovrtx/ovstream USD viewer. Use for requests like "prepare this streamed USD viewer for robot inspection", "add focus, semantic, and Lidar inspection controls", "inspect the Memory Cube / R-17 in the portal", or "add a Lidar evidence panel". Orchestrates the pinned ovrtx and Omniverse Realtime Viewer skills; it does not build a viewer, renderer, or stream. Use even when the user names only one of the three modes.
---

# R17 Inspection Mode

Layer up to three inspection modes onto a viewer that already streams: **focus** (frame one target), **semantic** (segmentation view), **Lidar** (optional evidence panel). This skill only sequences other skills and states the invariants; version-specific API details live in the pinned skills below, which are the source of truth. Read them instead of relying on memory. If they disagree with this file, they win.

If no streamed viewer exists yet, stop and route to `../omniverse-realtime-viewer/SKILL.md` (`references/routing.md`). Do not build one here.

## Invariants (check every step against these)

- **Source USD is immutable.** Cameras, labels, sensors, render vars and material defaults go in application-owned layers (session/composite wrapper, `over` prims), never in the scene file.
- **One renderer owner, one stream.** Only the existing render loop calls `renderer.step()`, mutates the stage, or writes attributes. Modes change what that loop does; they never add a renderer, a video track, or a client-side 3D fallback.
- **Native input and commands are separate channels.** Pointer/wheel/key traffic stays on the native input path. Inspection controls are JSON `{event_type, payload}` commands that are queued for the render thread. Never send mouse movement as JSON, and never do stage work inside an input callback. See `../omniverse-realtime-viewer/references/viewer-input-routing/README.md`.
- **Additive messages.** New events reuse the envelope and compatibility rules in `.../references/streaming-messages/README.md`; keep payloads under its size cap; send current state on connect.
- **Reset on stage load.** Focus target, active AOV and Lidar state are cleared with selection whenever a stage loads or resets.

## Workflow

Do steps 1-2 always, then only the modes requested. Each step names what to read; do not paste their code here.

1. **Survey, read-only.** Find the renderer owner, composite/session layer, camera prim path, RenderProduct, existing AOV state machine, and message router. Reuse them. Note the stage up-axis and units. Report gaps before changing anything.
2. **Resolve the target** with `../stage-queries/SKILL.md` unless the user gave an exact path. Ask if more than one prim matches.
3. **Focus camera.** Reuse the existing camera prim; change only how its pose is computed. Bounds scoped to the target subtree, then a fit-distance and row-major pose: `omniverse-realtime-viewer/references/{camera-auto-select,stage-hierarchy,camera-controls}`, written per `../writing-transforms/SKILL.md`. Keep a way back to the default view.
4. **Semantic view.** Author labels as `over` prims (`../semantic-labels/SKILL.md`), request outputs on the RenderProduct (`../camera-outputs-rt2/SKILL.md`), and switch through the existing AOV pipeline (`.../references/aov-switching`), converting to BGRA8 before streaming. Do not add a parallel toggle. Verify readback with `../reading-render-output/SKILL.md`.
5. **Lidar panel (only if asked).** Author sensor and `PointCloud` product in the app layer (`../configuring-lidar-sensors/SKILL.md`), read with `../reading-sensor-pointclouds/SKILL.md`, interpret with `../interpreting-lidar-pointclouds/SKILL.md`. Send a small summary (valid count, nearest range) over the data channel. Never stream raw points or a second video. Step the sensor only while the panel is enabled.
6. **Runtime toggles** that change attributes after load use `../writing-attributes/SKILL.md`. Output-defining Lidar attributes are authored before load, not mutated.
7. **Validate** per `.../references/validation.md`: nonblank focused frame, semantic frame with several distinct IDs and the target visible, Lidar summary with a nonzero valid count, plus one native orbit that still works after each mode switch.

Read `references/r17-field-notes.md` before steps 3-5; it holds the pitfalls already paid for on the Attic Portal.

## Planning-only requests

When asked to plan, or when the live portal must not change: do steps 1-2 read-only, then return a plan and stop. The plan lists the skills read, the layers and prims to author, the messages to add or reuse, and the validation evidence. Do not edit, restart, or connect to the running viewer without explicit approval.

## Limits

Not a viewer builder, a point-cloud visualizer, or a picking/selection skill (use `../picking-selection/SKILL.md` and the viewer's picking references for that).
