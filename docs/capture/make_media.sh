#!/usr/bin/env bash
# Encode frame sequences from capture_attic_portal.py into MP4 (<=15 s) and a
# palette-optimized GIF (<=640 px wide). Frames are played at the measured
# capture rate, so playback is real time.
set -euo pipefail
M="$(cd "$(dirname "$0")/../media/physical_ai_agent" && pwd)"
for name in cube-link perception physics; do
  F="$M/_frames/$name"; FPS="$(cat "$F/fps.txt")"
  ffmpeg -y -loglevel error -framerate "$FPS" -i "$F/%04d.png" \
    -vf "scale=1280:-2,format=yuv420p" -c:v libx264 -crf 24 -movflags +faststart "$M/$name.mp4"
  ffmpeg -y -loglevel error -framerate "$FPS" -i "$F/%04d.png" \
    -vf "scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=4" "$M/$name.gif"
done
