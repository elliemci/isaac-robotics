"""Starter helpers for R-17 Robot Vision semantic segmentation.

Use this with the installed ovrtx semantic-labels, camera-outputs-rt2,
reading-render-output, and stepping-and-rendering skills. The runtime-tested
sourceName is ``SemanticSegmentation`` with ``SemanticIdMap``. Do not use
``SemanticSegmentationSD`` for this Robot Vision feature.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import ovrtx
import warp as wp
from pxr import Usd, UsdGeom

R17_SEMANTICS_LAYER = Path('usd/R17_Semantics.usda')
BEAUTY_OUTPUT = 'LdrColor'
SEMANTIC_OUTPUT = 'SemanticSegmentation'
SEMANTIC_ID_MAP_OUTPUT = 'SemanticIdMap'
R17_RENDER_MODES = {'BEAUTY', 'SEMANTIC'}
MEMORY_CUBE_PATH = '/Root/Workshop/Cube'


def semantic_render_product_children() -> str:
    """Return RenderProduct children/orderedVars snippet for Robot Vision.

    Put these RenderVars under the existing camera RenderProduct, keep the
    existing LdrColor RenderVar, and stream one persistent BGRA buffer.
    """

    return """rel orderedVars = [
    </Render/Vars/LdrColor>,
    <SemanticSegmentation>,
    <SemanticIdMap>,
]

def RenderVar "SemanticSegmentation"
{
    string sourceName = "SemanticSegmentation"
}

def RenderVar "SemanticIdMap"
{
    string sourceName = "SemanticIdMap"
}
"""


def query_attic_environment_roots(base_stage: Path) -> list[str]:
    """Return per-object roots to label under /Root/Geometry.

    Labeling each child with its own label gives ovrtx multiple semantic IDs
    and visible candy-color object regions instead of one scene-wide color.
    """

    try:
        stage = Usd.Stage.Open(str(base_stage))
    except Exception:
        stage = None
    if stage is None:
        return []
    geometry = stage.GetPrimAtPath('/Root/Geometry')
    if not geometry or not geometry.IsValid():
        return []
    return sorted(str(child.GetPath()) for child in geometry.GetChildren() if UsdGeom.Imageable(child))


def _semantic_api_block(indent: str, semantic_class: str, semantic_label: str) -> str:
    return '\n'.join([
        f'{indent}string semantic:class:params:semanticData = "{semantic_class}"',
        f'{indent}string semantic:class:params:semanticType = "class"',
        f'{indent}string semantic:label:params:semanticData = "{semantic_label}"',
        f'{indent}string semantic:label:params:semanticType = "label"',
    ])


def write_r17_semantics_layer(
    path: Path,
    *,
    root_path: str = '/Root',
    cube_path: str = MEMORY_CUBE_PATH,
    environment_paths: list[str],
) -> None:
    """Author app-owned SemanticsAPI overrides without touching source USD."""

    path.parent.mkdir(parents=True, exist_ok=True)
    root_name = (root_path.strip('/').split('/') or ['Root'])[-1]
    cube_parts = [part for part in cube_path.strip('/').split('/') if part]
    if cube_parts != [root_name, 'Workshop', 'Cube']:
        raise RuntimeError(f'unexpected cube path for starter semantics: {cube_path}')

    geometry_children: list[str] = []
    for prim_path in environment_paths:
        parts = [part for part in prim_path.strip('/').split('/') if part]
        if len(parts) == 3 and parts[0] == root_name and parts[1] == 'Geometry':
            geometry_children.append(parts[2])

    lines = ['#usda 1.0', '', f'over "{root_name}"', '{']
    lines.extend(['    over "Geometry"', '    {'])
    for child_name in sorted(set(geometry_children)):
        lines.extend([
            f'        over "{child_name}" (',
            '            prepend apiSchemas = ["SemanticsAPI:label", "SemanticsAPI:class"]',
            '        )',
            '        {',
            _semantic_api_block('            ', 'attic_environment', child_name),
            '        }',
            '',
        ])
    lines.extend(['    }', ''])
    lines.extend([
        '    over "Workshop"',
        '    {',
        '        over "Cube" (',
        '            prepend apiSchemas = ["SemanticsAPI:label", "SemanticsAPI:class"]',
        '        )',
        '        {',
        _semantic_api_block('            ', 'retrieval_target', 'memory_cube'),
        '        }',
        '    }',
        '}',
        '',
    ])
    path.write_text('\n'.join(lines), encoding='utf-8')


def decode_semantic_id_map_tensor(tensor: np.ndarray) -> dict[int, str]:
    data = np.ascontiguousarray(tensor).view(np.uint8).reshape(-1)
    if data.size < 4:
        return {}
    entry_dtype = np.dtype([('id', '<u4', (4)), ('label_length', '<u4'), ('label_offset', '<u4')])
    num_entries = int.from_bytes(data[-4:].tobytes(), byteorder='little')
    entries_size = num_entries * entry_dtype.itemsize
    if num_entries <= 0 or entries_size > data.size - 4:
        return {}
    entries = data[:entries_size].view(entry_dtype).reshape(num_entries)
    labels_by_id: dict[int, str] = {}
    for entry in entries:
        semantic_id = int(entry['id'][0])
        label_offset = int(entry['label_offset'])
        label_length = int(entry['label_length'])
        label_end = label_offset + label_length
        if 0 <= label_offset < label_end <= data.size:
            labels_by_id[semantic_id] = data[label_offset:label_end].tobytes().decode('utf-8', errors='replace').rstrip('\x00').rstrip()
    return labels_by_id


def candy_colorize_semantic_ids(ids: np.ndarray, height: int, width: int) -> np.ndarray:
    """Convert ovrtx uint32 semantic IDs to display-ready BGRA candy colors."""

    ids = np.asarray(ids, dtype=np.uint32).reshape(height, width)
    mask = ids != 0
    palette = np.array([
        [255, 70, 70, 255],
        [120, 80, 255, 255],
        [20, 220, 255, 255],
        [210, 110, 170, 255],
        [90, 255, 90, 255],
        [0, 140, 255, 255],
        [255, 210, 0, 255],
        [180, 255, 60, 255],
    ], dtype=np.uint8)
    color_index = np.mod(ids, np.uint32(len(palette))).astype(np.int64)
    out = np.asarray(palette[color_index], dtype=np.uint8).reshape(height, width, 4)
    out[~mask] = np.array([0, 0, 0, 255], dtype=np.uint8)
    return np.ascontiguousarray(out, dtype=np.uint8)


def update_semantic_id_map(frame: Any) -> dict[int, str]:
    if SEMANTIC_ID_MAP_OUTPUT not in frame.render_vars:
        return {}
    with frame.render_vars[SEMANTIC_ID_MAP_OUTPUT].map(device=ovrtx.Device.CPU) as mapped:
        return decode_semantic_id_map_tensor(np.from_dlpack(mapped).copy())


def semantic_ids_from_frame(frame: Any, height: int, width: int) -> tuple[np.ndarray, list[int], int]:
    """Map ovrtx SemanticSegmentation and return ids, unique IDs, nonzero count."""

    if SEMANTIC_OUTPUT not in frame.render_vars:
        raise RuntimeError('SemanticSegmentation output missing')
    with frame.render_vars[SEMANTIC_OUTPUT].map(device=ovrtx.Device.CPU) as mapped:
        ids = np.from_dlpack(mapped).copy()
    if ids.shape != (height, width, 1) or ids.dtype != np.uint32:
        raise RuntimeError(f'bad SemanticSegmentation tensor: shape={ids.shape} dtype={ids.dtype}')
    flat = ids.reshape(-1)
    unique_ids = [int(value) for value in np.unique(flat)[:64]]
    nonzero_pixels = int(np.count_nonzero(flat))
    return ids, unique_ids, nonzero_pixels


def copy_numpy_bgra_to_stream(bgra_np: np.ndarray, stream_bgra: Any, *, height: int, width: int) -> bool:
    """Copy display-ready CPU BGRA into the persistent CUDA ovstream buffer."""

    bgra_np = np.ascontiguousarray(bgra_np, dtype=np.uint8)
    if bgra_np.shape != (height, width, 4):
        return False
    temp = wp.array(bgra_np, dtype=wp.uint8, device='cuda:0')
    wp.copy(stream_bgra, temp)
    wp.synchronize_device('cuda:0')
    return True
