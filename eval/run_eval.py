"""Replay every scenario against the running service and score it: the M1 gate (detection) and the
M2 gate (grounded answers). With --prep, the Phase 2P gate (prepared cards). M3 measures join in Phase 3.

Run from the repo root with the service, DynamoDB Local and Ollama running:
    backend/.venv/bin/python eval/run_eval.py [--prep] [scenario-name ...]

With --prep, each scenario is first prepared like a real meeting: its agenda (eval/scenarios/<name>/agenda.md)
and attendees become a prepared meeting, its cards are built, and the replay holds that meeting. Every top match
is judged (does the prepared question ask the same thing as the question asked?), which gives the wrong-hit
count and a threshold sweep. A --prep run writes docs/eval-results-prep.md and leaves the live report alone.

For each scenario: save its user's profile through the API, upload its prep pack (the documents in
eval/scenarios/<name>/), start a replayed session, press Attention where the timeline says so, collect
every event until the service stops, remove the documents again, then score. Alerts are scored against
the timeline labels. Cards are judged by the local answer model against what the user actually said next
and the documents: correct, relevant, cue at most 20 words, no invented personal facts; each cited source
is checked against the point it backs. Your own profile is put back afterwards. Results go to
docs/eval-results.md and eval/results/latest.json; every card is listed for manual review.
"""

import asyncio
import json
import sys
import time
from datetime import date

import httpx
import websockets

from synth import AUDIO, REPO, SCENARIOS

sys.path.insert(0, str(REPO / "backend"))
from app.adapters.factory import make_llm  # noqa: E402
from app.config import settings  # noqa: E402
from app.ports import Message  # noqa: E402

SERVICE = "http://127.0.0.1:8080"
WS = "ws://127.0.0.1:8080/ws"
RESULTS = REPO / "eval" / "results"
REPORT = REPO / "docs" / "eval-results.md"
PREP_REPORT = REPO / "docs" / "eval-results-prep.md"
PREP_TIMEOUT_S = 900
SWEEP = [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]

EARLY_S = 1.0          # an alert may start this long before the question line starts (lookback, partials)
LATE_S = 1.5           # or this long after it ends (the final text arriving)
ATTENTION_DELAY_S = 0.5   # how long after the line a scripted Attention press happens
MAX_CUE_WORDS = 20

TARGETS = {
    "detected": "at least 8 of 10 (report the gap to 10 of 10)",
    "false_alarms_per_30min": "15 or fewer (aim much lower)",
    "alert_p50_s": "1.0 s or less from the end of speech",
    "first_line": "p50 3 s or less, p90 4 s or less, from the end of speech",
    "quality": "7 of 10 good enough to say out loud",
    "source_accuracy": "9 of 10 cited sources support their point",
    "invented_facts": "0",
}

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "correct": {"type": "boolean"},
        "relevant": {"type": "boolean"},
        "invented_personal_facts": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["correct", "relevant", "invented_personal_facts", "reason"],
}
SAME_SCHEMA = {
    "type": "object",
    "properties": {"same": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["same", "reason"],
}
SUPPORT_SCHEMA = {
    "type": "object",
    "properties": {"supported": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["supported", "reason"],
}


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))]


def fmt(value, suffix=""):
    return "" if value is None else f"{value}{suffix}"


# ---------------------------------------------------------------- the prep pack

def pack_documents(name: str) -> list:
    return [p for p in sorted((SCENARIOS / name).glob("*.md")) if p.name != "agenda.md"]


async def upload_prep_pack(http: httpx.AsyncClient, name: str) -> list[str]:
    """Upload the scenario's documents (not the agenda, which is for Phase 2P) and return their ids."""
    ids = []
    for path in pack_documents(name):
        response = await http.post("/api/documents", files={"file": (path.name, path.read_bytes(), "text/markdown")})
        response.raise_for_status()
        ids.append(response.json()["docId"])
    return ids


async def remove_documents(http: httpx.AsyncClient, ids: list[str]) -> None:
    for doc_id in ids:
        await http.delete(f"/api/documents/{doc_id}")


def documents_text(name: str) -> str:
    return "\n\n".join(f"[{p.name}]\n{p.read_text().strip()}" for p in pack_documents(name))


# ---------------------------------------------------------------- replay

async def prepare(http: httpx.AsyncClient, timeline: dict) -> tuple[str, dict]:
    """Prepare the scenario like a real meeting and build its cards. Returns the meeting id and how it went."""
    agenda = (SCENARIOS / timeline["name"] / "agenda.md").read_text()
    attendees = sorted({line["who"] for line in timeline["lines"] if line["who"] != "me"})
    meeting = (await http.post("/api/prep", json={"title": timeline["title"], "agenda": agenda, "participants": attendees})).json()
    base = f"/api/prep/{meeting['sessionId']}"
    await http.post(f"{base}/build")
    deadline = time.perf_counter() + PREP_TIMEOUT_S
    while time.perf_counter() < deadline:
        status = (await http.get(f"{base}/status")).json()
        if status["state"] in ("done", "failed"):
            break
        await asyncio.sleep(2)
    cards = (await http.get(f"{base}/cards")).json()["cards"]
    return meeting["sessionId"], {"state": status["state"], "seconds": status["seconds"], "cards": len(cards), "error": status["error"]}


async def replay(timeline: dict, prep_session_id: str | None = None) -> list[dict]:
    """Run one scenario in replay mode and return every event the service sent."""
    attention_lines = [line for line in timeline["lines"] if line["attention_after"]]
    events: list[dict] = []
    async with websockets.connect(WS, max_size=None) as ws:
        start = {"type": "start", "replay_file": f"{timeline['name']}.wav", "one_on_one": timeline.get("one_on_one", False)}
        if prep_session_id:
            start["prep_session_id"] = prep_session_id
        await ws.send(json.dumps(start))
        started_at = None

        async def press_attention():
            for line in attention_lines:
                await asyncio.sleep(max(0.0, started_at + line["end_s"] + ATTENTION_DELAY_S - time.perf_counter()))
                await ws.send(json.dumps({"type": "attention"}))

        presser = None
        while True:
            event = json.loads(await ws.recv())
            events.append(event)
            if event["type"] == "started":
                started_at = time.perf_counter()
                presser = asyncio.create_task(press_attention())
            if event["type"] == "stopped" or (event["type"] == "error" and started_at is None):
                break
        if presser:
            presser.cancel()
    return events


# ---------------------------------------------------------------- M1 scoring

def score(timeline: dict, events: list[dict]) -> dict:
    lines = timeline["lines"]
    questions = [line for line in lines if line["label"] == "question_for_user"]
    first_seen: dict[str, dict] = {}
    last_seen: dict[str, dict] = {}
    for event in events:
        if event["type"] == "alert":
            first_seen.setdefault(event["id"], event)
            last_seen[event["id"]] = event
    kept = [last_seen[i] for i in last_seen if last_seen[i]["status"] != "retracted"]
    retracted = [last_seen[i] for i in last_seen if last_seen[i]["status"] == "retracted"]

    def window_end(line):
        # A question the host then hands to the user ("Surya, do you want to take that one?") may be
        # alerted on either line, so the question's window runs through the handoff.
        index = lines.index(line)
        following = lines[index + 1] if index + 1 < len(lines) else None
        return following["end_s"] if following and following["label"] == "handoff" else line["end_s"]

    def alerts_for(line):
        return [a for a in kept if line["start_s"] - EARLY_S <= a["start_s"] <= window_end(line) + LATE_S]

    detected, missed, latencies, duplicates = [], [], [], []
    used = set()
    for question in questions:
        matches = alerts_for(question)
        if matches:
            alert = min(matches, key=lambda a: first_seen[a["id"]]["at_s"])
            used.add(alert["id"])
            for extra in matches:   # a second card for the same question is a duplicate, not a false alarm
                if extra["id"] != alert["id"] and extra["id"] not in used:
                    used.add(extra["id"])
                    duplicates.append({"question": question["text"], "card": extra["question"], "reasons": first_seen[extra["id"]]["reasons"]})
            latencies.append(round(first_seen[alert["id"]]["at_s"] - question["end_s"], 2))
            detected.append({"text": question["text"], "alert_id": alert["id"], "alert_s": first_seen[alert["id"]]["at_s"] - question["end_s"],
                             "reasons": first_seen[alert["id"]]["reasons"], "category": alert["category"]})
        else:
            heard = [e["text"] for e in events if e["type"] == "turn" and e["channel"] == "them"
                     and abs(e["end_s"] - question["end_s"]) <= 2.0]
            was_retracted = [a for a in retracted if question["start_s"] - EARLY_S <= a["start_s"] <= question["end_s"] + LATE_S]
            missed.append({"text": question["text"], "heard": heard, "retracted": bool(was_retracted)})

    false_alarms = []
    for alert in kept:
        if alert["id"] in used:
            continue
        line = next((l for l in lines if l["start_s"] - EARLY_S <= alert["start_s"] <= l["end_s"] + LATE_S), None)
        false_alarms.append({"question": alert["question"], "reasons": first_seen[alert["id"]]["reasons"],
                             "line": line["text"] if line else "(between lines)", "label": line["label"] if line else ""})

    turn_delays = [e["delay_s"] for e in events if e["type"] == "turn" and e["channel"] == "them"]
    classifier_ms = [e["classifier_ms"] for e in events if e["type"] == "latency" and e["classifier_ms"] is not None]
    minutes = timeline["duration_s"] / 60
    return {
        "name": timeline["name"], "title": timeline["title"], "minutes": round(minutes, 2),
        "questions": len(questions), "detected": len(detected), "missed": missed, "detected_detail": detected,
        "false_alarms": false_alarms, "false_alarms_per_30min": round(len(false_alarms) * 30 / minutes, 1),
        "duplicates": duplicates,
        "alert_latencies_s": latencies, "turn_delays_s": turn_delays, "classifier_ms": classifier_ms,
        "retracted": len(retracted),
    }


# ---------------------------------------------------------------- M2 grading

class Judge:
    """The local answer model grades cards. Its verdicts are a first pass; the report lists every card for a human."""

    def __init__(self):
        self.llm = make_llm()
        self.model = settings.llm_answer_model

    async def ask(self, prompt: str, schema: dict) -> dict:
        """One retry after a timeout: a judge prompt with a large document pack can outlast the client's limit once."""
        try:
            return await self.llm.complete_json(self.model, [Message("user", prompt)], schema)
        except httpx.ReadTimeout:
            print("  (judge timed out, asking again)", flush=True)
            return await self.llm.complete_json(self.model, [Message("user", prompt)], schema)

    async def grade(self, question: str, truth: str | None, card: dict, documents: str, transcript: str) -> dict:
        points = "\n".join(f"- {p['text']}" for p in card["points"])
        prompt = (
            "You grade a cue card a meeting copilot showed to its user, who had just been asked a question.\n"
            "correct: every statement on the card agrees with the user's documents, with what the user actually answered, "
            "or with what was said in the meeting transcript. A true fact from the documents that goes beyond the question "
            "is still correct.\n"
            "relevant: the card answers the question that was asked.\n"
            "invented_personal_facts: statements about the user's own work, numbers, results, projects, ownership or "
            "decisions that appear in none of the documents, the user's answer or the transcript. A fact that is in the "
            "documents is never invented, even if the user did not say it. A misspelled name is not an invented fact. "
            "General knowledge that is not presented as the user's own fact is not invented.\n"
            "Reply only with the JSON asked for.\n\n"
            f"QUESTION: {question}\n"
            f"WHAT THE USER ACTUALLY ANSWERED: {truth or '(the user did not answer in the transcript)'}\n"
            f"MEETING TRANSCRIPT SO FAR:\n{transcript}\n\n"
            f"USER'S DOCUMENTS:\n{documents}\n\n"
            f"CARD LINE: {card['line'] or '(withheld, low confidence)'}\nCARD POINTS:\n{points or '(none)'}\n"
            f"CARD CONFIDENCE: {card['confidence']}"
        )
        return await self.ask(prompt, JUDGE_SCHEMA)

    async def same_question(self, asked: str, prepared: str) -> bool:
        prompt = (
            "A meeting copilot prepared a card for one question and is deciding whether to show it for another. "
            "same: true if the prepared card's question asks for the same information as the question that was asked, "
            "so its answer would answer it. Reply only with the JSON asked for.\n\n"
            f"QUESTION ASKED: {asked}\nPREPARED QUESTION: {prepared}"
        )
        return bool((await self.ask(prompt, SAME_SCHEMA))["same"])

    async def supports(self, point: str, source_text: str) -> bool:
        prompt = (
            "Does the SOURCE text support the POINT, meaning the point can be read from the source without adding facts? "
            "Reply only with the JSON asked for.\n\n"
            f"POINT: {point}\nSOURCE: {source_text}"
        )
        return bool((await self.ask(prompt, SUPPORT_SCHEMA))["supported"])


def truth_for(timeline: dict, question_line: dict) -> str | None:
    """What the user said right after the question: the ground truth for the card."""
    lines = timeline["lines"]
    index = lines.index(question_line)
    for line in lines[index + 1:index + 3]:
        if line["who"] == "me":
            return line["text"]
    return None


async def grade_cards(judge: Judge, timeline: dict, events: list[dict], detected: list[dict]) -> list[dict]:
    """One grade per detected question."""
    done = {e["alert_id"]: e for e in events if e["type"] == "answer_done"}
    matches = {e["alert_id"]: e for e in events if e["type"] == "cache_match" and e.get("score") is not None}
    latencies = {}
    for e in events:
        if e["type"] == "latency":
            latencies[e["alert_id"]] = e
    documents = documents_text(timeline["name"])
    grades = []
    for item in detected:
        card_event = done.get(item["alert_id"])
        if not card_event:
            grades.append({"question": item["text"], "line": None, "points": [], "good": False, "why": "no card was produced",
                           "cited": [], "invented": [], "first_line_s": None, "cue_words": 0})
            continue
        card = card_event["card"]
        question_line = next(l for l in timeline["lines"] if l["text"] == item["text"])
        truth = truth_for(timeline, question_line)
        spoken_so_far = "\n".join(f"{l['who']}: {l['text']}" for l in timeline["lines"] if l["end_s"] <= question_line["end_s"])
        verdict = await judge.grade(item["text"], truth, card, documents, spoken_so_far)
        words = len((card["line"] or "").split())
        cited = []
        for point in card["points"]:
            for number in point["sources"]:
                source = next((s for s in card_event["sources"] if s["number"] == number), None)
                if source:
                    cited.append({"point": point["text"], "source": f"{source['document']}, {source['location']}",
                                  "supported": await judge.supports(point["text"], source["text"])})
        invented = verdict["invented_personal_facts"]
        has_content = bool(card["line"] or card["points"])
        good = bool(verdict["correct"] and verdict["relevant"] and words <= MAX_CUE_WORDS and not invented and has_content)
        latency = latencies.get(item["alert_id"], {})
        match = matches.get(item["alert_id"])
        grades.append({
            "label": card_event.get("label"),
            "match": {"score": match["score"], "hit": match["hit"], "prepared_question": match["prepared_question"],
                      "same": await judge.same_question(item["text"], match["prepared_question"])} if match else None,
            "question": item["text"], "truth": truth, "line": card["line"], "points": [p["text"] for p in card["points"]],
            "confidence": card["confidence"], "tags": card["tags"],
            "sources": [f"{s['document']}, {s['location']}" for s in card_event["sources"]],
            "cue_words": words, "correct": verdict["correct"], "relevant": verdict["relevant"], "invented": invented,
            "why": verdict["reason"], "cited": cited, "good": good,
            "first_line_s": latency.get("last_word_to_first_answer_s"), "card_done_s": latency.get("last_word_to_answer_done_s"),
        })
    return grades


# ---------------------------------------------------------------- summary, gates, report

def summarize(results: list[dict]) -> dict:
    latencies = [v for r in results for v in r["alert_latencies_s"]]
    turns = [v for r in results for v in r["turn_delays_s"]]
    classifier = [v for r in results for v in r["classifier_ms"]]
    minutes = sum(r["minutes"] for r in results)
    false_alarms = sum(len(r["false_alarms"]) for r in results)
    grades = [g for r in results for g in r.get("grades", [])]
    first_lines = [g["first_line_s"] for g in grades if g.get("first_line_s") is not None]
    cited = [c for g in grades for c in g.get("cited", [])]
    return {
        "questions": sum(r["questions"] for r in results), "detected": sum(r["detected"] for r in results),
        "false_alarms": false_alarms, "minutes": round(minutes, 1), "false_alarms_per_30min": round(false_alarms * 30 / minutes, 1),
        "duplicates": sum(len(r["duplicates"]) for r in results),
        "alert_p50_s": percentile(latencies, 0.5), "alert_p90_s": percentile(latencies, 0.9),
        "alerts_before_end_of_speech": sum(v <= 0 for v in latencies), "alerts_total": len(latencies),
        "turn_p50_s": percentile(turns, 0.5), "turn_p90_s": percentile(turns, 0.9),
        "classifier_p50_ms": percentile(classifier, 0.5),
        "graded": len(grades), "good_cards": sum(g["good"] for g in grades),
        "first_line_p50_s": percentile(first_lines, 0.5), "first_line_p90_s": percentile(first_lines, 0.9),
        "cited_points": len(cited), "supported_points": sum(c["supported"] for c in cited),
        "invented_facts": sum(len(g.get("invented", [])) for g in grades),
        "over_20_words": sum(1 for g in grades if (g.get("cue_words") or 0) > MAX_CUE_WORDS),
    }


def summarize_prep(results: list[dict]) -> dict:
    """Hits and misses on the detected questions, and how other thresholds would have done on the same matches."""
    grades = [g for r in results for g in r.get("grades", [])]
    matched = [g for g in grades if g.get("match")]
    hits = [g for g in grades if g.get("label") == "prepared"]
    misses = [g for g in grades if g.get("label") == "live"]
    sweep = []
    for threshold in SWEEP:
        would_hit = [g for g in matched if g["match"]["score"] >= threshold]
        sweep.append({"threshold": threshold, "hits": len(would_hit), "wrong": sum(not g["match"]["same"] for g in would_hit)})
    return {
        "detected": len(grades), "hits": len(hits), "wrong_hits": sum(1 for g in hits if g["match"] and not g["match"]["same"]),
        "hit_first_line_p50_s": percentile([g["first_line_s"] for g in hits if g["first_line_s"] is not None], 0.5),
        "miss_first_line_p50_s": percentile([g["first_line_s"] for g in misses if g["first_line_s"] is not None], 0.5),
        "good_hits": sum(g["good"] for g in hits), "good_misses": sum(g["good"] for g in misses), "misses": len(misses),
        "right_card_existed": sum(1 for g in matched if g["match"]["same"]),
        "prep_seconds": [r["prep"]["seconds"] for r in results], "prep_cards": [r["prep"]["cards"] for r in results],
        "sweep": sweep,
    }


def gate_prep(prep: dict) -> list[tuple[str, bool, str]]:
    detected = prep["detected"] or 1
    p50 = prep["hit_first_line_p50_s"]
    return [
        ("Cache hit rate on detected questions (aim: at least half)", prep["hits"] >= detected / 2, f"{prep['hits']} of {prep['detected']}"),
        ("Card latency on a hit, p50 from end of speech", p50 is not None and p50 <= 1.0, f"{p50} s"),
        ("Wrong cache hits", prep["wrong_hits"] == 0, f"{prep['wrong_hits']} of {prep['hits']}"),
    ]


def write_prep_report(results: list[dict], summary: dict, prep: dict) -> None:
    checks = gate_prep(prep)
    lines = [
        "# Eval results: prepared cards (Phase 2P)",
        "",
        f"Written by `eval/run_eval.py --prep` on {date.today().isoformat()}: {len(results)} scenarios, {summary['questions']} questions to the user. "
        f"Each scenario was prepared from its agenda and attendees, its cards built by the real models, and the replay held that meeting. "
        f"Hit threshold CACHE_HIT_SCORE = {settings.cache_hit_score}.",
        "",
        "| Measure | Gate | Local |",
        "|---|---|---|",
        f"| Cache hit rate on detected questions | report it; aim for at least half | {prep['hits']} of {prep['detected']} (the right prepared card existed for {prep['right_card_existed']}) |",
        f"| Card latency on a hit, p50 from end of speech | 1 s or less | {fmt(prep['hit_first_line_p50_s'], ' s')} |",
        f"| First cue line on a miss, p50 | 3 s or less | {fmt(prep['miss_first_line_p50_s'], ' s')} |",
        f"| Wrong cache hits (the prepared card answers a different question) | report it | {prep['wrong_hits']} of {prep['hits']} |",
        f"| Cards good enough to say out loud, hits / misses | 7 of 10 | {prep['good_hits']} of {prep['hits']} / {prep['good_misses']} of {prep['misses']} |",
        f"| Invented personal facts, all cards | 0 | {summary['invented_facts']} |",
        f"| Preparation time per scenario | a few minutes | {', '.join(f'{s:.0f} s' for s in prep['prep_seconds'])} ({', '.join(str(c) for c in prep['prep_cards'])} cards) |",
        "",
        "Prep gate: " + ("**passed**" if all(ok for _, ok, _ in checks) else "**not passed**") + ". "
        + "; ".join(f"{name}: {value} ({'ok' if ok else 'not ok'})" for name, ok, value in checks),
        "",
        "## Threshold sweep",
        "",
        "Every detected question's best match was judged: does the prepared question ask the same thing? The same matches at other thresholds:",
        "",
        "| Threshold | Hits | Wrong hits |",
        "|---|---|---|",
    ]
    lines += [f"| {s['threshold']:.2f} | {s['hits']} | {s['wrong']} |" for s in prep["sweep"]]
    lines += ["", "## Every match", ""]
    for r in results:
        for g in r.get("grades", []):
            m = g.get("match")
            if not m:
                continue
            lines.append(f"- **{r['title']}**: \"{g['question']}\" matched \"{m['prepared_question']}\" at {m['score']:.3f}, "
                         f"{'hit' if m['hit'] else 'miss'}, judged {'the same question' if m['same'] else 'a different question'}; "
                         f"card {g['label']}, first line {fmt(g['first_line_s'], ' s')}, {'good' if g['good'] else 'not good'}")
    lines.append("")
    PREP_REPORT.write_text("\n".join(lines))


def gate(summary: dict) -> list[tuple[str, bool, str]]:
    detected_ok = summary["detected"] >= 8 * summary["questions"] / 10
    return [
        ("Questions to the user detected", detected_ok, f"{summary['detected']} of {summary['questions']}"),
        ("False alarms per 30 min", summary["false_alarms_per_30min"] <= 15, f"{summary['false_alarms_per_30min']}"),
        ("Alert latency p50 from end of speech", summary["alert_p50_s"] is not None and summary["alert_p50_s"] <= 1.0,
         f"{summary['alert_p50_s']} s (p90 {summary['alert_p90_s']} s)"),
    ]


def gate_m2(summary: dict) -> list[tuple[str, bool, str]]:
    graded = summary["graded"] or 1
    quality_ok = summary["good_cards"] >= 0.7 * graded
    cited = summary["cited_points"]
    sources_ok = cited == 0 or summary["supported_points"] >= 0.9 * cited
    p50, p90 = summary["first_line_p50_s"], summary["first_line_p90_s"]
    return [
        ("First cue line from end of speech", p50 is not None and p50 <= 3.0 and p90 is not None and p90 <= 4.0, f"p50 {p50} s, p90 {p90} s"),
        ("Cards good enough to say out loud", quality_ok, f"{summary['good_cards']} of {summary['graded']}"),
        ("Cited sources that support their point", sources_ok, f"{summary['supported_points']} of {cited}"),
        ("Invented personal facts", summary["invented_facts"] == 0, f"{summary['invented_facts']}"),
    ]


def write_report(results: list[dict], summary: dict) -> None:
    m1, m2 = gate(summary), gate_m2(summary)
    verdict = lambda checks: ("**passed**" if all(ok for _, ok, _ in checks) else "**not passed**") + ". " + \
        "; ".join(f"{name}: {value} ({'ok' if ok else 'not ok'})" for name, ok, value in checks)
    lines = [
        "# Eval results",
        "",
        "Written by `eval/run_eval.py`. Local column: the full pipeline on the owner's Mac. AWS column: filled in Phase 4.",
        f"Last local run: {date.today().isoformat()}, {len(results)} scenarios, {summary['minutes']} minutes of meeting audio, "
        f"{summary['questions']} questions to the user, each scenario with its prep pack of documents uploaded.",
        "",
        "## M1: detect",
        "",
        "| Measure | Target | Local | AWS |",
        "|---|---|---|---|",
        f"| Questions to the user detected | {TARGETS['detected']} | {summary['detected']} of {summary['questions']} | |",
        f"| False alarms per 30 min | {TARGETS['false_alarms_per_30min']} | {summary['false_alarms_per_30min']} ({summary['false_alarms']} in {summary['minutes']} min) | |",
        f"| Alert latency from end of speech, p50 / p90 | {TARGETS['alert_p50_s']} | {fmt(summary['alert_p50_s'], ' s')} / {fmt(summary['alert_p90_s'], ' s')}, {summary['alerts_before_end_of_speech']} of {summary['alerts_total']} alerts fired before the speaker finished | |",
        f"| Turn known after the last word, p50 / p90 | 0.4 to 0.7 s | {fmt(summary['turn_p50_s'], ' s')} / {fmt(summary['turn_p90_s'], ' s')} | |",
        f"| Classifier time, p50 | report | {fmt(summary['classifier_p50_ms'], ' ms')} | |",
        f"| Duplicate cards for an already detected question | 0 (one card per question) | {summary['duplicates']} | |",
        "",
        "M1 gate: " + verdict(m1),
        "",
        "## M2: grounded answers (live path; prepared cards arrive with Phase 2P)",
        "",
        "| Measure | Target | Local | AWS |",
        "|---|---|---|---|",
        f"| First cue line from end of speech, p50 / p90 | {TARGETS['first_line']} | {fmt(summary['first_line_p50_s'], ' s')} / {fmt(summary['first_line_p90_s'], ' s')} | |",
        f"| Cards good enough to say out loud (judge: correct, relevant, cue at most 20 words, nothing invented) | {TARGETS['quality']} | {summary['good_cards']} of {summary['graded']} | |",
        f"| Cited sources that support their point | {TARGETS['source_accuracy']} | {summary['supported_points']} of {summary['cited_points']} | |",
        f"| Invented personal facts | {TARGETS['invented_facts']} | {summary['invented_facts']} | |",
        f"| Cue lines over 20 words | 0 | {summary['over_20_words']} | |",
        "",
        "M2 gate: " + verdict(m2),
        "",
        "The judge is the local answer model grading cards of its own kind, so its verdicts are a first pass. Every card is listed below for a human to review.",
        "",
        "## Per scenario",
        "",
        "| Scenario | Minutes | Questions | Detected | False alarms | Duplicates | Retracted by Detector B | Alert latencies from end of speech |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        latencies = ", ".join(f"{v:+.2f} s" for v in r["alert_latencies_s"])
        lines.append(f"| {r['title']} | {r['minutes']} | {r['questions']} | {r['detected']} | {len(r['false_alarms'])} | {len(r['duplicates'])} | {r['retracted']} | {latencies} |")
    lines += ["", "### Misses, false alarms and duplicates", ""]
    for r in results:
        for miss in r["missed"]:
            why = "alerted then retracted by Detector B" if miss["retracted"] else "no alert"
            lines.append(f"- {r['title']}, missed: \"{miss['text']}\" ({why}; heard: {' / '.join(miss['heard']) or 'nothing nearby'})")
        for fa in r["false_alarms"]:
            lines.append(f"- {r['title']}, false alarm on \"{fa['line']}\" [{fa['label']}]: card said \"{fa['question']}\" because of {', '.join(fa['reasons'])}")
        for dup in r["duplicates"]:
            lines.append(f"- {r['title']}, duplicate card for \"{dup['question']}\": second card said \"{dup['card']}\" because of {', '.join(dup['reasons'])}")
    if not any(r["missed"] or r["false_alarms"] or r["duplicates"] for r in results):
        lines.append("- none")
    lines += ["", "Negative latencies mean the card appeared before the speaker had finished (Detector A fired on a partial). "
              "Latencies around 3 s are questions Detector A was unsure about and Detector B promoted after reading the final text."]
    lines += ["", "### Cards, for manual review", ""]
    for r in results:
        for g in r.get("grades", []):
            if g["line"] is None and not g["points"]:
                lines.append(f"- **{r['title']}**: \"{g['question']}\": {g['why']}")
                continue
            flags = [k for k, v in g["tags"].items() if v]
            unsupported = sum(1 for c in g["cited"] if not c["supported"])
            lines += [
                f"- **{r['title']}**: \"{g['question']}\" ({'good' if g['good'] else 'not good'}; first line {fmt(g['first_line_s'], ' s')}, "
                f"confidence {g['confidence']}" + (f", tags: {', '.join(flags)}" if flags else "") + ")",
                f"  - User actually said: {g['truth'] or '(no answer in the transcript)'}",
                f"  - Card: **{g['line'] or '(line withheld)'}** " + " ".join(f"| {p}" for p in g["points"]),
                f"  - Sources: {', '.join(g['sources']) or 'none'}" + (f"; unsupported citations: {unsupported} of {len(g['cited'])}" if g["cited"] else ""),
                f"  - Judge: correct {g['correct']}, relevant {g['relevant']}" + (f", invented: {g['invented']}" if g["invented"] else "") + f". {g['why']}",
            ]
    lines.append("")
    REPORT.write_text("\n".join(lines))


# ---------------------------------------------------------------- main

async def main():
    prep_mode = "--prep" in sys.argv[1:]
    wanted = {a for a in sys.argv[1:] if not a.startswith("--")}
    timelines = [json.loads(p.read_text()) for p in sorted(AUDIO.glob("*.timeline.json"))]
    timelines = [t for t in timelines if not wanted or t["name"] in wanted]
    if not timelines:
        sys.exit("no timelines found: run eval/generate_audio.py first")

    async with httpx.AsyncClient(base_url=SERVICE, timeout=60) as http:
        health = (await http.get("/api/health")).json()
        print(f"service: {health}")
        original = await http.get("/api/profile")
        judge = Judge()
        results = []
        try:
            for timeline in timelines:
                await http.put("/api/profile", json=timeline["user"])
                doc_ids = await upload_prep_pack(http, timeline["name"])
                print(f"\n{timeline['title']} ({timeline['duration_s']} s, {len(doc_ids)} documents) ...", flush=True)
                prep_id, prep = None, None
                try:
                    if prep_mode:
                        prep_id, prep = await prepare(http, timeline)
                        print(f"  prepared: {prep}", flush=True)
                    events = await replay(timeline, prep_id)
                finally:
                    if prep_id:
                        await http.delete(f"/api/prep/{prep_id}")
                    await remove_documents(http, doc_ids)
                result = score(timeline, events)
                result["prep"] = prep
                result["events"] = events   # kept in the raw results so a run can be re-scored without replaying
                print(f"  detected {result['detected']} of {result['questions']}, false alarms {len(result['false_alarms'])}, "
                      f"alert latencies {result['alert_latencies_s']}")
                for miss in result["missed"]:
                    print(f"  MISSED: {miss['text']}  heard: {miss['heard']}  retracted: {miss['retracted']}")
                for fa in result["false_alarms"]:
                    print(f"  FALSE ALARM on \"{fa['line']}\": {fa['question']} ({', '.join(fa['reasons'])})")
                result["grades"] = await grade_cards(judge, timeline, events, result["detected_detail"])
                for g in result["grades"]:
                    if g["line"] is None and not g["points"]:
                        print(f"  NO CARD: {g['question']}")
                        continue
                    if g.get("match"):
                        m = g["match"]
                        print(f"  match {m['score']:.3f} {'HIT' if m['hit'] else 'miss'} ({'same' if m['same'] else 'DIFFERENT'}): {m['prepared_question']}")
                    print(f"  {'good' if g['good'] else 'NOT GOOD'} [{g.get('label')}] ({fmt(g['first_line_s'], ' s')}): {g['question']}\n"
                          f"      card: {g['line']} | {' | '.join(g['points'])}\n"
                          f"      judge: correct {g['correct']}, relevant {g['relevant']}, invented {g['invented']}; {g['why'][:140]}")
                results.append(result)
        finally:
            if original.status_code == 200:
                await http.put("/api/profile", json=original.json())

    summary = summarize(results)
    RESULTS.mkdir(exist_ok=True)
    if prep_mode:
        prep = summarize_prep(results)
        (RESULTS / "latest-prep.json").write_text(json.dumps({"summary": summary, "prep": prep, "scenarios": results}, indent=2))
        for result in results:
            result.pop("events")
        write_prep_report(results, summary, prep)
        print("\nsummary:", json.dumps(summary, indent=2), "\nprep:", json.dumps(prep, indent=2))
        for name, ok, value in gate_prep(prep):
            print(f"  {'ok ' if ok else 'NOT'} {name}: {value}")
        print(f"\nreport written to {PREP_REPORT.relative_to(REPO)}")
        return
    (RESULTS / "latest.json").write_text(json.dumps({"summary": summary, "scenarios": results}, indent=2))
    for result in results:
        result.pop("events")
    write_report(results, summary)
    print("\nsummary:", json.dumps(summary, indent=2))
    for name, ok, value in gate(summary) + gate_m2(summary):
        print(f"  {'ok ' if ok else 'NOT'} {name}: {value}")
    print(f"\nreport written to {REPORT.relative_to(REPO)}")


if __name__ == "__main__":
    asyncio.run(main())
