#!/usr/bin/env bash
# Usage: make_media_clip.sh <frames_dir> <out_basename> <frames_per_second>
# Encodes recorder frames (sampled every 1/fps s of simulation time, so playback is real time)
# to MP4 (<=15 s) and a palette-optimized GIF (640 px wide, 10 fps).
set -euo pipefail
F="$1"; OUT="$2"; FPS="$3"
ffmpeg -y -loglevel error -framerate "$FPS" -i "$F/%05d.png" -t 15 -vf "scale=1280:-2,format=yuv420p" -c:v libx264 -crf 28 -movflags +faststart "$OUT.mp4"
ffmpeg -y -loglevel error -framerate "$FPS" -i "$F/%05d.png" -t 15 -vf "fps=8,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=64[p];[b][p]paletteuse=dither=bayer:bayer_scale=4" "$OUT.gif"
