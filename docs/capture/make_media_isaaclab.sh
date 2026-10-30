#!/usr/bin/env bash
# Usage: make_media_isaaclab.sh <frames_dir> <out_basename>
# Encodes the PNG frames from capture_isaaclab_rollout.py to MP4 (<=15 s) and a
# palette-optimized GIF (<=640 px wide) at the capture rate (real time).
set -euo pipefail
F="$1"; OUT="$2"; FPS="$(cat "$F/fps.txt")"
GIF_FPS=10
ffmpeg -y -loglevel error -framerate "$FPS" -i "$F/%04d.png" -t 15 \
  -vf "scale=1280:-2,format=yuv420p" -c:v libx264 -crf 22 -movflags +faststart "$OUT.mp4"
ffmpeg -y -loglevel error -framerate "$FPS" -i "$F/%04d.png" -t 15 \
  -vf "fps=$GIF_FPS,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=4" "$OUT.gif"
