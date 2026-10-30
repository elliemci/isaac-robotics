# R17 field notes (Attic Portal)

Findings that the pinned skills do not state. Confirm against the pinned skills and the live build before relying on them.

## Camera
- Attic stage is Z-up; build poses with world up (0,0,1), not the Y-up default.
- Keep the focus camera as a viewer-owned prim in the app layer and write the active viewer camera; never write the scene.
- Frame the envelope of every pose the target can take, not just its home pose, and clamp a minimum distance so the target keeps context.

## Semantic
- Use `SemanticSegmentation` with `SemanticIdMap`. Do not substitute `SemanticSegmentationSD`.
- Label each environment child separately. One scene-wide label yields one flat color and a useless view.
- Keep the beauty `LdrColor` var in `orderedVars`; semantic mode swaps what is streamed, it does not rebuild the stage.

## Lidar
- The sensor looks down local -Z with +Y up, like a camera. Aiming local +X at the target points it at the floor.
- Output frame `SENSOR`: +X forward, +Y left, +Z up.
- Materials with no nonvisual base give no returns. Author defaults for unlabeled materials as `over` prims in the app layer.
- Lidar toggling must be stable: exercise on/off repeatedly before calling it done.
- Evidence to show: valid point count and nearest range; clear both when disabled.

## Protocol shape used
- Command event `r17-command-v1`, state event `r17-state-v1`, commands `camera.setView`, `render.setMode`, `lidar.setEnabled`; state carries `status` (WAITING/APPLYING/READY/ERROR). Reuse the host app's own names if it already has a scheme.
