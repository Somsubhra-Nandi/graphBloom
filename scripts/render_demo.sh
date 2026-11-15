#!/bin/sh
# Merge the recorded frames (video/raw) with the voiceover into video/graphbloom_demo.mp4.
# 1080p, 30 fps, H.264 + AAC, 0.5 s fade-in, 1 s fade-out. Frame 0 is audio time 0 (record_demo.py aligns them).
set -e
cd "$(dirname "$0")/.."
END=$(python3 -c "import json;print(json.load(open('video/timings.json'))['audio_duration']+1.0)")
ffmpeg -y -v error -f concat -safe 0 -i video/raw/frames.txt -i video/voiceover.mp3 \
  -vf "scale=1920:1080,fps=30,fade=t=in:st=0:d=0.5,fade=t=out:st=$(python3 -c "print($END-1.0)"):d=1,format=yuv420p" \
  -af "apad" -t "$END" \
  -c:v libx264 -preset veryfast -crf 20 -r 30 -c:a aac -b:a 160k -movflags +faststart video/graphbloom_demo.mp4
ls -la video/graphbloom_demo.mp4
