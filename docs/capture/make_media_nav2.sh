#!/usr/bin/env bash
# Usage: make_media_nav2.sh <frames_dir> <out_dir>
# Frames are sampled every 0.1 s of simulation time; the video plays them 4x faster
# (so the ~59 s sequence fits in 15 s). Also writes three PNG stills.
set -euo pipefail
F="$1"; D="$2"; SPEED_FPS=40
ffmpeg -y -loglevel error -framerate $SPEED_FPS -i "$F/%05d.png" -t 15 \
  -vf "scale=1280:-2,format=yuv420p" -c:v libx264 -crf 23 -movflags +faststart "$D/nav2-lesson-4x.mp4"
ffmpeg -y -loglevel error -framerate $SPEED_FPS -i "$F/%05d.png" -t 15 \
  -vf "fps=10,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer:bayer_scale=4" "$D/nav2-lesson-4x.gif"
cp "$F/00090.png" "$D/01-carter-arrives-at-table.png"
cp "$F/00120.png" "$D/02-limo-on-table-cube.png"
cp "$F/00215.png" "$D/03-cube-pushed-carter-leaves.png"
