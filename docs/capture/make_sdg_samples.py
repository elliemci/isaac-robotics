"""Pick a few annotated frames from a generated palletjack_data folder and draw their KITTI boxes.

Usage: python3 make_sdg_samples.py <palletjack_data_dir> <samples_out_dir> [frames_per_set]
Copies rgb + KITTI label for the chosen frames (only frames with at least one pallet jack) and
writes samples_out_dir/overlays/<set>.png with the boxes drawn. Source data is only read.
"""
import shutil
import sys
from pathlib import Path
from PIL import Image, ImageDraw

src, out = Path(sys.argv[1]), Path(sys.argv[2])
n = int(sys.argv[3]) if len(sys.argv) > 3 else 2
for ds in sorted(p for p in src.iterdir() if (p / "Camera").is_dir()):
    cam = ds / "Camera"
    labelled = []
    for lab in sorted(cam.joinpath("object_detection").glob("*.txt"), key=lambda p: int(p.stem)):
        rows = [l.split() for l in lab.read_text().splitlines() if l.strip()]
        area = sum((float(r[6]) - float(r[4])) * (float(r[7]) - float(r[5])) for r in rows)
        if rows and area >= 20000:  # skip frames where a jack is only a sliver at the edge
            labelled.append((int(lab.stem), rows))
    step = max(1, len(labelled) // (n + 1))
    picks = [labelled[(i + 1) * step] for i in range(n)]
    for k, (idx, rows) in enumerate(picks):
        (out / ds.name / "rgb").mkdir(parents=True, exist_ok=True)
        (out / ds.name / "object_detection").mkdir(parents=True, exist_ok=True)
        shutil.copy(cam / "rgb" / f"{idx}.png", out / ds.name / "rgb" / f"{idx}.png")
        shutil.copy(cam / "object_detection" / f"{idx}.txt", out / ds.name / "object_detection" / f"{idx}.txt")
        if k == 0:
            img = Image.open(cam / "rgb" / f"{idx}.png").convert("RGB")
            d = ImageDraw.Draw(img)
            for r in rows:  # KITTI: class trunc occ alpha x1 y1 x2 y2 ...
                x1, y1, x2, y2 = map(float, r[4:8])
                d.rectangle([x1, y1, x2, y2], outline=(118, 185, 0), width=3)
                d.text((x1 + 4, max(0, y1 - 14)), r[0], fill=(118, 185, 0))
            (out / "overlays").mkdir(parents=True, exist_ok=True)
            img.save(out / "overlays" / f"{ds.name}.png")
    print(ds.name, [i for i, _ in picks], "of", len(labelled), "labelled frames")
