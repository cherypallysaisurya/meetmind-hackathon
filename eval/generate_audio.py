"""Build the eval audio: one stereo WAV plus a timeline per scenario in eval/scenarios.

Run from the repo root:
    backend/.venv/bin/python eval/generate_audio.py [scenario-name ...]
"""

import sys

from synth import SCENARIOS, build, load_scenario, save


def main():
    wanted = set(sys.argv[1:])
    for path in sorted(SCENARIOS.glob("*.yaml")):
        if wanted and path.stem not in wanted:
            continue
        scenario = load_scenario(path)
        left, right, timeline = build(scenario)
        wav = save(scenario, left, right, timeline)
        questions = sum(line["label"] == "question_for_user" for line in timeline)
        print(f"{wav.name}: {len(left) / 16000:.1f} s, {len(timeline)} lines, {questions} questions for the user")


if __name__ == "__main__":
    main()
