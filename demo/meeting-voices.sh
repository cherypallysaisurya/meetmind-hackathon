#!/bin/zsh
# The other people in the demo meeting, Priya and Dan, spoken by macOS voices through the Mac's audio output.
# MeetMind captures that output as the meeting channel, exactly as it would capture Meet or Zoom.
# The meeting is a review of MeetMind itself, with MeetMind's own docs as the user's documents.
#
# Start listening in MeetMind, then run this. The five lines play by themselves, with time between them for the
# card and for your answer. After them, type any question of your own; Dan asks it. An empty line ends.
#
# A screen recording with the microphone does not hear the Mac's own output, so every line is also kept as a file
# in data/demo-voices/ with the moment it started playing, to lay the voices onto the recording afterwards.

PAUSE_S=${PAUSE_S:-14}

lines=(
  "Karen|Thanks everyone for joining. Surya, which Meta models are you running in the demo?"
  "Daniel|And Surya, your app joins the call as a bot to listen in, right?"
  "Karen|I'm sharing the repo now. Surya, what do you make of this table?"
  "Daniel|Surya, how do you know it's answering from your docs and not inventing things?"
  "Karen|Great work. Any questions before we wrap up?"
)

out=${0:A:h}/../data/demo-voices
mkdir -p "$out"
: > "$out/played.txt"
n=0

speak() {   # voice, text
  n=$((n + 1))
  say -v "$1" -o "$out/line$n.aiff" "$2"
  echo "line$n.aiff $(perl -MTime::HiRes=time -e 'printf "%.3f", time')" >> "$out/played.txt"
  echo "$2"
  afplay "$out/line$n.aiff"
}

for line in "${lines[@]}"; do
  speak "${line%%|*}" "${line#*|}"
  sleep "$PAUSE_S"
done

while read "?Your own question for Dan (Enter on an empty line ends): " question && [ -n "$question" ]; do
  speak Daniel "$question"
done
