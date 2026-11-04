"""The session orchestrator owns one meeting session.

It takes the client's control messages and audio frames, runs them through the pipeline, and sends
events back over the same WebSocket. The pipeline so far: frame accounting, speech-to-text,
end-of-turn detection, Detector A (rules) with the Attention button, Detector B (the classifier),
the grounded answer agent, the notes agent (the meeting's memory), latency telemetry and the meeting
record in the store.

Client to server: JSON {"type": "start"} or {"type": "start", "replay_file": "name.wav"} (the service
plays that test meeting itself and stops at its end); a start may name "prep_session_id", a meeting prepared
ahead of time, whose record (title, agenda, participants) the session then uses; {"type": "attention"}, {"type": "one_on_one", "on": true}
(a meeting of two: every question from the other side is for the user; also accepted as "one_on_one" in
the start message), {"type": "use_documents", "on": false} (answers from the model alone, for a talk where the
user's documents do not apply; also accepted in the start message), {"type": "see_screen", "on": true} (a question
that points at the screen gets a picture of it; also accepted in the start message), {"type": "screen", "alert_id",
"jpeg"} (the picture asked for, base64, or null when the app could not take it), {"type": "doubt"} (the user asks for
a question to ask), {"type": "stop"}, and binary frames
(see audio/frames.py).
Server to client: {"type": "started", "session_id"}, {"type": "stats", ...} once per second of audio,
{"type": "transcript", "channel", "text", "is_partial", "start_s", "end_s"},
{"type": "turn", "channel", "text", "start_s", "end_s", "delay_s"} when a speaker finished,
{"type": "alert", "id", "question", "score", "reasons", "start_s", "at_s", "is_final", "status", "category",
"confidence"} when Detector A thinks a question is for the user: status "candidate" first, then "confirmed"
or "retracted" once Detector B has read the final text,
{"type": "answer_delta", "alert_id", "card": {line, points, partial, confidence}} while the cue card is written,
{"type": "answer_done", "alert_id", "card", "sources": [{number, document, location, text}], "label": "live" or "prepared"},
{"type": "notes_update", "notes": [...]} every NOTES_EVERY_S of audio and once more at stop,
{"type": "cache_match", "alert_id", "question", "hit", "score", "card_id", "prepared_question", "matched_phrasing",
"edited"} in a prepared meeting, before the card (Phase 2P);
{"type": "screen_request", "alert_id"} when a question points at the screen and See my screen is on (decision 0009);
{"type": "doubt", "id", "question", "why", "sources", "reason"} a question the user could ask, on an open floor ("any
questions?") or when asked; question null when there is nothing new to ask (only sent when the user asked);
{"type": "latency", "alert_id", "question", "status", "last_word_to_alert_s", "last_word_to_turn_s",
"last_word_to_classified_s", "classifier_ms", "last_word_to_first_answer_s", "last_word_to_answer_done_s"}
once a question's timing is complete,
{"type": "stopped", ...}, {"type": "error", "message": ...}.
"""

import asyncio
import base64
import json
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Awaitable, Callable
from uuid import uuid4

from ..audio.frames import FRAME_BYTES, FRAME_SECONDS, level_db, split_channels, sum_of_squares
from ..agents.answer import AnswerAgent, asks_to_agree
from ..agents.claims import ClaimChecker
from ..agents.doubts import REPEAT_SIMILARITY, DoubtAgent, nothing_to_ask
from ..agents.notes import NotesAgent
from ..audio.replay import frames_at_real_time, resolve
from ..config import settings
from ..detect.classifier import Classifier
from ..detect.rules import RulesDetector, is_handoff, is_open_floor, looks_like_question, refers_to_screen, with_real_name
from ..ports import LLM, THEM, Embeddings, PrepCard, Profile, SpeechToText, Store, Transcript, User, VectorStore
from ..ports import Session as SessionRecord
from ..ports import SessionItem
from ..prep.cache import prep_collection
from ..telemetry.latency import QuestionTiming
from ..telemetry.log import log_event
from ..turns.end_of_turn import EndOfTurnDetector, Turn

Send = Callable[[dict], Awaitable[None]]
MakeSpeechToText = Callable[[], SpeechToText]

STATS_EVERY_FRAMES = 10   # one second of audio
SAME_UTTERANCE_S = 0.6    # partials and the final of one utterance start within this of each other
RECENT_QUESTION_S = 10.0  # Attention pressed this soon after a them turn means "that one"
HANDOFF_LOOKBACK_S = 30.0 # "Surya, do you want to take that one?" hands over a question asked within this long
DUPLICATE_WINDOW_S = 45.0 # a question asked again (or handed over) within this long is the same card
DUPLICATE_SIMILARITY = 0.75
EDITED_CARD_BONUS = 0.03  # between two close prepared cards, the one the user edited wins (it is approved)
SCREEN_WAIT_S = 1.5       # how long a card waits for the picture of the screen before it is written without it
DOUBT_EVERY_S = 180.0     # at most one question to ask every 3 minutes of audio (spec); the user's own request is not limited
DOUBT_LOOKBACK_S = 180.0  # the doubt agent reads the last three minutes of the conversation


def make_claim_checker(llm: LLM, embeddings: Embeddings, vectors: VectorStore) -> ClaimChecker | None:
    if not settings.claim_context_chars:
        return None
    return ClaimChecker(llm, embeddings, vectors, settings.llm_answer_model, settings.claim_context_chars)


@dataclass
class Alert:
    id: str
    start_s: float
    heard: str                         # what them said, with the user's name put right; Detector B judges this
    question: str                      # what the card answers: the same, or the earlier question a handoff passes on
    is_final: bool = True              # cards are only ever opened on a complete sentence (decision 0007)
    score: float = 0.0
    reasons: list[str] | None = None
    status: str = "candidate"          # candidate (shown), pending (not shown, Detector B decides), confirmed or retracted
    category: str | None = None
    confidence: float | None = None


class Session:
    def __init__(self, send: Send, make_stt: MakeSpeechToText, store: Store, llm: LLM, embeddings: Embeddings,
                 vectors: VectorStore, user: User, retention_days: int):
        self.send = send
        self.make_stt = make_stt
        self.embeddings = embeddings   # the cache matcher embeds each question (Phase 2P)
        self.vectors = vectors
        self.store = store
        self.classifier = Classifier(llm, settings.llm_classifier_model, settings.classifier_min_confidence)
        self.answer_agent = AnswerAgent(llm, embeddings, vectors, settings.llm_answer_model, settings.retrieval_top_k,
                                        settings.retrieval_min_score, make_claim_checker(llm, embeddings, vectors))
        self.notes_agent = NotesAgent(llm, settings.llm_answer_model)
        self.doubt_agent = DoubtAgent(llm, embeddings, settings.llm_doubt_model)
        self.user = user
        self.retention_days = retention_days
        self.started = False
        self.profile: Profile | None = None
        self.record: SessionRecord | None = None
        self.frames = 0
        self.attention_at_s: float | None = None   # audio clock when the user last pressed Attention
        self.one_on_one = False
        self.use_documents = True
        self.see_screen = False
        self.screens: dict[str, asyncio.Future] = {}   # alert id to the picture of the screen it is waiting for
        self.prep_cards: dict[str, PrepCard] = {}   # the prepared meeting's cards, by id (Phase 2P)
        self.stt: SpeechToText | None = None
        self.turns = EndOfTurnDetector()
        self.rules: RulesDetector | None = None
        self.alerts: list[Alert] = []              # alerts of this session, newest last
        self.timings: dict[str, QuestionTiming] = {}
        self.answered: set[str] = set()
        self.classifying: set[asyncio.Task] = set()
        self.answering: dict[str, asyncio.Task] = {}   # alert id to the task writing its card
        self.cards_done: list[dict] = []               # question, cue and points of finished cards, for follow-ups
        self.notes: list[str] = []
        self.notes_through_s = 0.0                     # the notes cover turns that ended before this audio time
        self.notes_at_s = 0.0                          # when the notes were last rewritten
        self.noting: asyncio.Task | None = None
        self.doubts: list[str] = []                    # questions suggested to the user in this meeting
        self.doubt_at_s: float | None = None           # audio time of the last one shown
        self.suggesting: asyncio.Task | None = None
        self.replayer: asyncio.Task | None = None
        self.forwarder: asyncio.Task | None = None
        self._reset_level_sums()

    def _reset_level_sums(self):
        self.sum_squares = {"me": 0.0, "them": 0.0}
        self.level_samples = 0

    def audio_now_s(self) -> float:
        """The audio clock: how many seconds of audio have arrived so far."""
        return self.frames * FRAME_SECONDS

    def expires_at(self) -> int:
        return int(time.time()) + self.retention_days * 24 * 3600

    async def handle_text(self, text: str) -> None:
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            await self.send({"type": "error", "message": "control message is not JSON"})
            return
        kind = message.get("type")
        if kind == "start":
            self.one_on_one = bool(message.get("one_on_one", False))
            self.use_documents = bool(message.get("use_documents", True))
            self.see_screen = bool(message.get("see_screen", False))
            replay_file = message.get("replay_file")
            try:
                replay_path = resolve(settings.path("replay_dir"), replay_file) if replay_file else None
            except FileNotFoundError as error:
                await self.send({"type": "error", "message": str(error)})
                return
            await self._start(message.get("prep_session_id"))
            if self.started and replay_path:
                self.replayer = asyncio.create_task(self._replay(replay_path))
        elif kind == "attention":
            await self._attention()
        elif kind == "one_on_one":
            self.one_on_one = bool(message.get("on"))
            if self.rules:
                self.rules.one_on_one = self.one_on_one
            log_event("one_on_one", on=self.one_on_one)
        elif kind == "use_documents":
            self.use_documents = bool(message.get("on"))
            log_event("use_documents", on=self.use_documents)
        elif kind == "see_screen":
            self.see_screen = bool(message.get("on"))
            log_event("see_screen", on=self.see_screen)
        elif kind == "screen":
            waiting = self.screens.get(message.get("alert_id"))
            if waiting and not waiting.done():
                jpeg = message.get("jpeg")
                waiting.set_result(base64.b64decode(jpeg) if jpeg else None)
        elif kind == "doubt":
            self._suggest_later(asked=True)
        elif kind == "stop":
            await self._stop()
        else:
            await self.send({"type": "error", "message": f"unknown message type {kind!r}"})

    async def handle_frame(self, frame: bytes) -> None:
        if not self.started:
            await self.send({"type": "error", "message": "audio received before start"})
            return
        if len(frame) != FRAME_BYTES:
            await self.send({"type": "error", "message": f"frame of {len(frame)} bytes, expected {FRAME_BYTES}"})
            return
        me, them = split_channels(frame)
        self.frames += 1
        self.sum_squares["me"] += sum_of_squares(me)
        self.sum_squares["them"] += sum_of_squares(them)
        self.level_samples += len(me)
        if self.frames % STATS_EVERY_FRAMES == 0:
            await self.send({
                "type": "stats",
                "frames": self.frames,
                "audio_seconds": round(self.audio_now_s(), 1),
                "me_db": round(level_db(self.sum_squares["me"], self.level_samples), 1),
                "them_db": round(level_db(self.sum_squares["them"], self.level_samples), 1),
            })
            self._reset_level_sums()
            self._maybe_update_notes()
        if self.stt:
            await self.stt.feed(frame)

    async def _replay(self, path) -> None:
        """Play a test meeting into this session as if it were live audio, then stop."""
        try:
            async for frame in frames_at_real_time(path):
                if not self.started:
                    return
                await self.handle_frame(frame)
        except ValueError as error:
            await self.send({"type": "error", "message": str(error)})
        if self.started:
            self.replayer = None
            await self._stop()

    async def close(self) -> None:
        """The client went away: stop the pipeline without sending anything."""
        self.started = False
        if self.replayer:
            self.replayer.cancel()
            self.replayer = None
        if self.forwarder:
            self.forwarder.cancel()
            self.forwarder = None
        for task in self.answering.values():
            task.cancel()
        self.answering = {}
        if self.noting:
            self.noting.cancel()
            self.noting = None
        if self.suggesting:
            self.suggesting.cancel()
            self.suggesting = None
        if self.stt:
            await self.stt.stop()
            self.stt = None
        await self._close_record()

    async def _start(self, prep_session_id: str | None = None) -> None:
        if self.started:
            await self.send({"type": "error", "message": "session already started"})
            return
        self.profile = await self.store.get_profile(self.user.user_id)
        if self.profile is None:
            await self.send({"type": "error", "message": "no profile saved yet, fill in the Profile screen first"})
            return
        now = int(time.time())
        prepared = await self.store.get_session(self.user.user_id, prep_session_id) if prep_session_id else None
        if prep_session_id and prepared is None:
            await self.send({"type": "error", "message": "the prepared meeting was not found; prepare it again on the Prepare tab"})
            return
        self.prep_cards = {}
        if prepared:
            self.record = prepared   # the meeting prepared ahead of time is now held
            self.record.started_at, self.record.ended_at, self.record.ttl = now, None, self.expires_at()
            self.prep_cards = {c.card_id: c for c in await self.store.list_prep_cards(prepared.session_id)}
        else:
            self.record = SessionRecord(
                user_id=self.user.user_id, session_id=uuid4().hex,
                title=time.strftime("Meeting on %b %d, %Y at %H:%M", time.localtime(now)),
                started_at=now, ended_at=None, summary="", todos=[], ttl=self.expires_at(),
            )
        await self.store.save_session(self.record)
        self.frames = 0
        self._reset_level_sums()
        self.turns = EndOfTurnDetector()
        self.alerts = []
        self.cards_done = []
        self.notes, self.notes_through_s, self.notes_at_s = [], 0.0, 0.0
        self.doubts, self.doubt_at_s = [], None
        self.attention_at_s = None
        self.rules = RulesDetector(
            aliases=[self.profile.display_name, *self.profile.aliases], topics=self.profile.topics,
            attention_window_s=settings.attention_window_s, after_you_spoke_window_s=settings.after_you_spoke_window_s,
        )
        self.rules.one_on_one = self.one_on_one
        self.stt = self.make_stt()
        await self.stt.start()
        self.forwarder = asyncio.create_task(self._forward_transcripts())
        self.started = True
        self.timings = {}
        asyncio.create_task(self._prime_answer_model())
        log_event("session_started", session_id=self.record.session_id, user=self.user.user_id)
        await self.send({"type": "started", "session_id": self.record.session_id})

    async def _stop(self) -> None:
        self.started = False
        if self.replayer:
            self.replayer.cancel()
            self.replayer = None
        if self.stt:
            await self.stt.stop()          # flushes the last words, then ends the transcript stream
            self.stt = None
        if self.forwarder:
            await self.forwarder             # every transcript is sent before "stopped"
            self.forwarder = None
        await self._drain_background_work(seconds=20)
        if self._unnoted_turns():
            await self._update_notes()   # the notes catch up with the end of the meeting
        await self._close_record()
        if self.record:
            log_event("session_stopped", session_id=self.record.session_id, audio_seconds=round(self.audio_now_s(), 1),
                      alerts=len(self.alerts), confirmed=sum(a.status == "confirmed" for a in self.alerts))
        await self.send({"type": "stopped", "frames": self.frames, "audio_seconds": round(self.audio_now_s(), 1)})

    async def _drain_background_work(self, seconds: float) -> None:
        """Wait for classifier, card and notes tasks, including the ones they spawn (a classifier verdict can
        start a redone card), until none is left or the time is up."""
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            pending = set(self.classifying) | set(self.answering.values()) | {t for t in (self.noting, self.suggesting) if t}
            if not pending:
                return
            await asyncio.wait(pending, timeout=deadline - time.perf_counter())

    async def _close_record(self) -> None:
        if self.record and self.record.ended_at is None:
            self.record.ended_at = int(time.time())
            await self.store.save_session(self.record)

    async def _forward_transcripts(self) -> None:
        assert self.stt
        async for transcript in self.stt.transcripts():
            await self.send({
                "type": "transcript",
                "channel": transcript.channel,
                "text": transcript.text,
                "is_partial": transcript.is_partial,
                "start_s": transcript.start_s,
                "end_s": transcript.end_s,
            })
            if transcript.channel == THEM:
                await self._detect(transcript)
            turn = self.turns.on_transcript(transcript, self.audio_now_s())
            if turn:
                await self._remember_turn(turn)
                log_event("turn", channel=turn.channel, text=turn.text, end_s=turn.end_s, delay_s=turn.delay_s, echo=turn.echo)
                await self.send({
                    "type": "turn",
                    "channel": turn.channel,
                    "text": turn.text,
                    "start_s": turn.start_s,
                    "end_s": turn.end_s,
                    "delay_s": turn.delay_s,
                })

    # Detector A

    async def _detect(self, transcript: Transcript) -> None:
        """Run the rules on a them sentence once it is complete. Partials are ignored: a card written for half a
        sentence answers the wrong thing, as the first real meeting showed (decision 0007)."""
        assert self.rules
        if transcript.is_partial:
            return
        if is_open_floor(transcript.text):
            self._suggest_later(asked=False)
            return   # "any questions?" invites a question from the user; it is not one to answer
        you_spoke = self.turns.last_turn("me", ended_before_s=transcript.start_s)
        candidate = self.rules.evaluate(
            transcript.text, now_s=self.audio_now_s(), started_s=transcript.start_s,
            you_spoke_at_s=you_spoke.end_s if you_spoke else None, attention_at_s=self.attention_at_s,
        )
        if candidate.fires:
            self.attention_at_s = None   # an Attention press is used up by the first alert it helps
            before = len(self.alerts)
            await self._open_alert(transcript.start_s, self._heard(transcript.text), candidate.score, candidate.reasons)
            if len(self.alerts) == before:
                return   # folded into an existing card
            alert = self.alerts[-1]
            self._stamp_final(alert, transcript)
            if self._answer_right_away(alert):
                self._answer_later(alert)   # the classifier follows the first cue line
            else:
                self._classify_later(alert)
        elif candidate.weak:
            # Not sure enough to show anything. Detector B reads the sentence; a card appears only if it agrees.
            self._classify_later(self._pending_alert(transcript, candidate))

    def _heard(self, text: str) -> str:
        """What them said, with a misheard version of the user's name put right."""
        assert self.rules and self.profile
        return with_real_name(text, self.rules.aliases, self.profile.display_name)

    def _question_in(self, text: str, start_s: float) -> str:
        """The question an utterance puts to the user: the text itself or, for a handoff ("Surya, do you want to
        take that one?"), the question somebody asked just before it. The card is then written for the real
        question from the start instead of for the handoff sentence."""
        if not is_handoff(text):
            return text
        for turn in reversed(self.turns.recent(HANDOFF_LOOKBACK_S, start_s)):
            asked_before = turn.channel == THEM and turn.end_s <= start_s
            if asked_before and turn.text.rstrip().endswith("?") and not is_handoff(turn.text):
                return turn.text
        return text

    async def _attention(self) -> None:
        """Attention pressed. Just after a them turn it means that question; otherwise it arms the next one."""
        now = self.audio_now_s()
        last = self.turns.last_turn(THEM)
        current = self.alerts[-1] if self.alerts else None
        already_alerted = current is not None and last is not None and abs(current.start_s - last.start_s) <= SAME_UTTERANCE_S
        if last and now - last.end_s <= RECENT_QUESTION_S and not already_alerted and not self.turns.is_speaking(THEM):
            before = len(self.alerts)
            await self._open_alert(last.start_s, self._heard(last.text), 0.6, ["attention"])
            if len(self.alerts) > before:
                alert = self.alerts[-1]
                timing = self.timings[alert.id]
                timing.last_word_s, timing.turn_known_s = last.end_s, last.end_s + last.delay_s
                self._answer_later(alert)
        else:
            self.attention_at_s = now

    def _same_question_as(self, question: str, except_id: str | None = None) -> Alert | None:
        """An open card from the last 45 s of audio asking the same thing, if any. One card per question."""
        now = self.audio_now_s()
        for other in reversed(self.alerts):
            if other.id == except_id or other.status in ("retracted", "pending") or now - other.start_s > DUPLICATE_WINDOW_S:
                continue
            if SequenceMatcher(None, other.question.lower(), question.lower()).ratio() >= DUPLICATE_SIMILARITY:
                return other
        return None

    async def _open_alert(self, start_s: float, heard: str, score: float, reasons: list[str]) -> None:
        question = self._question_in(heard, start_s)
        duplicate = self._same_question_as(question)
        if duplicate:
            log_event("duplicate_folded", into=duplicate.id, question=question, reasons=reasons)
            return
        alert = Alert(id=uuid4().hex[:8], start_s=start_s, heard=heard, question=question)
        alert.score, alert.reasons = score, reasons
        self.alerts.append(alert)
        self.timings[alert.id] = QuestionTiming(alert.id, question, alert_s=round(self.audio_now_s(), 2))
        log_event("alert", alert_id=alert.id, question=question, score=score, reasons=reasons, at_s=round(self.audio_now_s(), 2))
        await self._send_alert(alert)

    def _pending_alert(self, transcript: Transcript, candidate) -> Alert:
        """A weak candidate: remembered but not shown. Detector B decides whether it becomes a card."""
        heard = self._heard(transcript.text)
        alert = Alert(id=uuid4().hex[:8], start_s=transcript.start_s, heard=heard, question=self._question_in(heard, transcript.start_s))
        alert.score, alert.reasons, alert.status = candidate.score, candidate.reasons, "pending"
        self.alerts.append(alert)
        self.timings[alert.id] = QuestionTiming(alert.id, alert.question)
        self._stamp_final(alert, transcript)
        log_event("weak_candidate", alert_id=alert.id, question=alert.question, score=candidate.score, reasons=candidate.reasons)
        return alert

    def _stamp_final(self, alert: Alert, transcript: Transcript) -> None:
        timing = self.timings[alert.id]
        timing.question = alert.question
        timing.last_word_s = transcript.end_s
        timing.turn_known_s = round(self.audio_now_s(), 2)

    async def _send_alert(self, alert: Alert) -> None:
        payload = {
            "type": "alert", "id": alert.id, "question": alert.question, "score": alert.score,
            "reasons": alert.reasons, "start_s": alert.start_s, "at_s": round(self.audio_now_s(), 2),
            "is_final": alert.is_final, "status": alert.status, "category": alert.category, "confidence": alert.confidence,
        }
        await self.send(payload)
        if alert.status != "candidate" and self.record:
            await self.store.add_item(SessionItem(
                session_id=self.record.session_id,
                timestamp=self.record.started_at * 1000 + int(self.audio_now_s() * 1000),
                type="alert", payload={k: v for k, v in payload.items() if k != "type"}, ttl=self.expires_at(),
            ))

    # Detector B

    @staticmethod
    def _question_changed(before: str, after: str) -> bool:
        return SequenceMatcher(None, before.lower(), after.lower()).ratio() < 0.6

    def _classify_later(self, alert: Alert) -> None:
        """Run the classifier without holding up the transcript stream."""
        if alert.status != "candidate" and alert.status != "pending":
            return
        if self.one_on_one and alert.status == "candidate" and looks_like_question(alert.heard):
            # A meeting of two: a question is for the user. Detector B would only be weeding out small talk here,
            # not worth five seconds of the shared GPU in a real call (decision 0007).
            task = asyncio.create_task(self._confirm_by_rules(alert))
            self.classifying.add(task)
            task.add_done_callback(self.classifying.discard)
            return
        if any(t.get_name() == alert.id for t in self.classifying):
            return
        task = asyncio.create_task(self._classify(alert), name=alert.id)
        self.classifying.add(task)
        task.add_done_callback(self.classifying.discard)

    async def _confirm_by_rules(self, alert: Alert) -> None:
        alert.status = "confirmed"
        alert.category = "question"
        await self._send_alert(alert)
        if alert.id not in self.answering and alert.id not in self.answered:
            self._answer_later(alert)
        timing = self.timings[alert.id]
        timing.classified_s = round(self.audio_now_s(), 2)
        timing.classifier_ms = 0
        timing.status, timing.question = alert.status, alert.question
        await self._send_timing(timing)

    async def _classify(self, alert: Alert) -> None:
        assert self.profile
        recent = self.turns.recent(60, self.audio_now_s())
        started = time.perf_counter()
        try:
            verdict = await self.classifier.classify(self.profile, recent, alert.heard, alert.reasons or [])
        except Exception as error:   # the alert stays as Detector A left it; the user still sees it
            log_event("classifier_failed", alert_id=alert.id, error=str(error))
            await self.send({"type": "error", "message": f"classifier failed: {error}"})
            return
        was_pending = alert.status == "pending"
        pressed_attention = "attention" in (alert.reasons or [])
        if pressed_attention:
            alert.status = "confirmed"   # the user asked for this card; the classifier only adds the category
        else:
            alert.status = "confirmed" if self.classifier.confirms(verdict, one_on_one=self.one_on_one) else "retracted"
        alert.category = verdict.category
        alert.confidence = round(verdict.confidence, 2)
        question_before = alert.question
        if alert.status == "confirmed" and verdict.question_text:
            alert.question = self._question_in(verdict.question_text, alert.start_s)
        twin = self._same_question_as(alert.question, except_id=alert.id) if alert.status == "confirmed" else None
        if twin and twin.start_s < alert.start_s:
            # The classifier recognised a question already on a card (a handoff, a repeat): fold this one into it.
            log_event("duplicate_folded", into=twin.id, question=alert.question, reasons=alert.reasons)
            alert.status = "retracted"
            self._cancel_answer(alert)
        if was_pending and alert.status == "confirmed":
            self.timings[alert.id].alert_s = round(self.audio_now_s(), 2)   # the card appears only now
            log_event("alert", alert_id=alert.id, question=alert.question, score=alert.score, reasons=alert.reasons, at_s=round(self.audio_now_s(), 2))
        if was_pending and alert.status == "retracted":
            log_event("weak_candidate_dropped", alert_id=alert.id, question=alert.question)
            return   # it was never shown, so there is nothing to retract on screen
        await self._send_alert(alert)
        if alert.status == "retracted":
            # Cancel the card only while nothing of it is on screen; once the cue line shows, the user may be reading it.
            if self.timings[alert.id].first_answer_s is None:
                self._cancel_answer(alert)
        elif self._question_changed(question_before, alert.question):
            # The classifier found the real question behind a handoff ("Surya, do you want to take that one?").
            # A card written for the handoff text is wrong, so it is written again for the real question.
            log_event("card_redone_for_real_question", alert_id=alert.id, was=question_before, now=alert.question)
            self._cancel_answer(alert)
            self.answered.discard(alert.id)
            self._answer_later(alert)
        elif alert.id not in self.answering and alert.id not in self.answered:
            self._answer_later(alert)   # a bare name mention, or a weak candidate, waited for this confirmation

        timing = self.timings[alert.id]
        timing.classified_s = round(self.audio_now_s(), 2)
        timing.classifier_ms = int((time.perf_counter() - started) * 1000)
        timing.status, timing.question = alert.status, alert.question
        await self._send_timing(timing)

    async def _send_timing(self, timing: QuestionTiming) -> None:
        """Sent when Detector B has answered, and again when the card is done, with the answer stages filled in."""
        log_event("latency", **{k: v for k, v in timing.event().items() if k != "type"})
        await self.send(timing.event())

    # Answer agent

    async def _prime_answer_model(self) -> None:
        assert self.profile
        started = time.perf_counter()
        try:
            await self.answer_agent.prime(self.profile)
            log_event("answer_model_primed", ms=int((time.perf_counter() - started) * 1000))
        except Exception as error:
            log_event("prime_failed", error=str(error))

    @staticmethod
    def _answer_right_away(alert: Alert) -> bool:
        """Start the card before Detector B answers when Detector A saw a question or the user pressed Attention.
        A bare name mention waits, so a non-question never gets a card that then vanishes."""
        return bool({"question", "attention"} & set(alert.reasons or []))

    def _answer_later(self, alert: Alert) -> None:
        """Start writing the card for the alert's current question; it is shown as it is written."""
        if alert.id in self.answering or alert.id in self.answered:
            return
        if self.noting:
            self.noting.cancel()   # the notes can wait; the card cannot
            self.noting = None
        task = asyncio.create_task(self._answer(alert))
        self.answering[alert.id] = task
        # Only forget the task that finished: a card cancelled and written again must not drop its replacement.
        task.add_done_callback(lambda t: self.answering.pop(alert.id, None) if self.answering.get(alert.id) is t else None)

    async def _show_card(self, alert: Alert, card: dict) -> None:
        timing = self.timings[alert.id]
        if card["line"] and timing.first_answer_s is None:
            timing.first_answer_s = round(self.audio_now_s(), 2)
        await self.send({"type": "answer_delta", "alert_id": alert.id, "card": card})
        if card["line"] or card["points"]:
            self._classify_later(alert)   # the classifier starts once something readable is on screen, not alongside the answer

    def _cancel_answer(self, alert: Alert) -> None:
        task = self.answering.pop(alert.id, None)
        if task:
            task.cancel()
            log_event("answer_cancelled", alert_id=alert.id)

    async def _prepared_card_for(self, alert: Alert) -> PrepCard | None:
        """The cache matcher: the prepared card whose question, or one of its phrasings, is closest in meaning.
        A hit needs settings.cache_hit_score; every decision is logged with its score so the threshold can be tuned."""
        if not self.prep_cards or not self.record:
            return None
        try:
            vector = (await self.embeddings.embed([alert.question]))[0]
            matches = await self.vectors.search(prep_collection(self.record.session_id), vector, 5)
        except Exception as error:
            log_event("cache_match_failed", alert_id=alert.id, error=str(error))
            return None   # the live card covers it
        candidates = [(m, self.prep_cards[m.metadata["card_id"]]) for m in matches if m.metadata.get("card_id") in self.prep_cards]
        if not candidates:
            log_event("cache_match", alert_id=alert.id, question=alert.question, hit=False, score=None)
            return None
        match, card = max(candidates, key=lambda mc: mc[0].score + (EDITED_CARD_BONUS if mc[1].user_edited else 0.0))
        hit = match.score >= settings.cache_hit_score
        decision = {"alert_id": alert.id, "question": alert.question, "hit": hit, "score": match.score, "card_id": card.card_id,
                    "prepared_question": card.predicted_question, "matched_phrasing": match.metadata.get("text"), "edited": card.user_edited}
        log_event("cache_match", **decision)
        await self.send({"type": "cache_match", **decision})   # the debug panel and the eval read it
        return card if hit else None

    async def _answer(self, alert: Alert) -> None:
        assert self.profile
        timing = self.timings[alert.id]
        # "Your pipeline handles PDFs now, right?" states something about the user's work: the claim checker settles it
        # from the documents. A card prepared for a nearby question ("When is PDF support landing?") would skip that check.
        prepared = None if asks_to_agree(alert.question) else await self._prepared_card_for(alert)
        if prepared:
            await self._show_card(alert, {**prepared.card, "partial": ""})
            await self._finish_card(alert, prepared.card, prepared.sources, "prepared", prepared_question=prepared.predicted_question)
            return
        recent = self.turns.recent(30, self.audio_now_s())
        screen = await self._screen_for(alert) if self.see_screen and refers_to_screen(alert.question) else None

        async def on_update(card: dict) -> None:
            await self._show_card(alert, card)

        try:
            card, sources = await self.answer_agent.answer(self.user.user_id, self.profile, alert.question, recent, on_update,
                                                           notes=self.notes, previous_cards=self.cards_done[-2:],
                                                           use_documents=self.use_documents, screen=screen)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log_event("answer_failed", alert_id=alert.id, error=str(error))
            await self.send({"type": "error", "message": f"answer failed: {error}"})
            return
        if timing.first_answer_s is None and card.snapshot()["line"]:
            await self._show_card(alert, card.snapshot())
        sources_given = [{"number": s.number, "document": s.document, "location": s.location, "text": s.text} for s in sources]
        await self._finish_card(alert, card.snapshot(), sources_given, "live")

    async def _screen_for(self, alert: Alert) -> bytes | None:
        """Ask the app for a picture of the screen and wait a moment for it. It lives only as long as this card."""
        waiting = asyncio.get_running_loop().create_future()
        self.screens[alert.id] = waiting
        started = time.perf_counter()
        await self.send({"type": "screen_request", "alert_id": alert.id})
        try:
            picture = await asyncio.wait_for(waiting, SCREEN_WAIT_S)
        except asyncio.TimeoutError:
            picture = None
        finally:
            self.screens.pop(alert.id, None)
        log_event("screen", alert_id=alert.id, received=picture is not None, kb=len(picture) // 1024 if picture else 0,
                  ms=int((time.perf_counter() - started) * 1000))
        return picture

    async def _finish_card(self, alert: Alert, card: dict, sources: list[dict], label: str, prepared_question: str | None = None) -> None:
        """The card is complete, written live or prepared: tell the client, remember it, store it, time it."""
        timing = self.timings[alert.id]
        self.answered.add(alert.id)
        self.cards_done.append({"question": alert.question, "line": card.get("line"), "points": [p["text"] for p in card.get("points", [])]})
        timing.answer_done_s = round(self.audio_now_s(), 2)
        self._classify_later(alert)   # in case nothing of the card was shown (low confidence, no line)
        cited = {n for p in card.get("points", []) for n in p["sources"]}
        payload = {"type": "answer_done", "alert_id": alert.id, "card": {**card, "partial": ""}, "label": label,
                   "sources": [s for s in sources if s["number"] in cited]}
        await self.send(payload)
        log_event("answer", alert_id=alert.id, label=label, line=card.get("line"), points=len(card.get("points", [])),
                  confidence=card.get("confidence"), sources=[f"{s['document']}, {s['location']}" for s in payload["sources"]],
                  **({"prepared_question": prepared_question} if prepared_question else {}))
        if self.record:
            await self.store.add_item(SessionItem(
                session_id=self.record.session_id,
                timestamp=self.record.started_at * 1000 + int(self.audio_now_s() * 1000),
                type="answer", payload={k: v for k, v in payload.items() if k != "type"} | {"question": alert.question},
                ttl=self.expires_at(),
            ))
        if timing.classified_s is not None:
            await self._send_timing(timing)

    # Doubt agent

    def _suggest_later(self, asked: bool) -> None:
        """A question for the user to ask: on an open floor at most every DOUBT_EVERY_S, or whenever the user asks."""
        now = self.audio_now_s()
        if self.suggesting:
            return
        if not asked and self.doubt_at_s is not None and now - self.doubt_at_s < DOUBT_EVERY_S:
            log_event("doubt_skipped", reason="one every 3 minutes", at_s=round(now, 2))
            return
        self.suggesting = asyncio.create_task(self._suggest(asked))
        self.suggesting.add_done_callback(lambda t: setattr(self, "suggesting", None))

    async def _suggest(self, asked: bool) -> None:
        assert self.profile
        reason = "asked" if asked else "open floor"
        recent = self.turns.recent(DOUBT_LOOKBACK_S, self.audio_now_s())
        # Compared with questions only: a good follow-up sits close to the statement it asks about (0.81 in a replay).
        asked_already = [t.text for t in recent if not t.echo and looks_like_question(t.text)] + self.doubts
        heard = " ".join(t.text for t in recent if t.channel == THEM and not t.echo)[-1500:]   # the latest of what others said
        quiet = nothing_to_ask(recent, asked)
        if quiet:
            log_event("no_doubt", reason=reason, why=quiet)
            if asked:
                await self.send({"type": "doubt", "id": uuid4().hex[:8], "question": None, "why": f"No question yet: {quiet}.",
                                 "sources": [], "reason": reason})
            return
        started = time.perf_counter()
        try:
            sources = await self.answer_agent.retrieve(self.user.user_id, heard) if self.use_documents and heard else []
            doubt = await self.doubt_agent.write(self.profile, recent, self.notes, sources, self.doubts)
            closest = await self.doubt_agent.closest(doubt.question, asked_already) if doubt else 0.0
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log_event("doubt_failed", error=str(error))
            if asked:
                await self.send({"type": "error", "message": f"suggesting a question failed: {error}"})
            return
        ms = int((time.perf_counter() - started) * 1000)
        if doubt and closest >= REPEAT_SIMILARITY:
            log_event("doubt_dropped", question=doubt.question, closest=round(closest, 3), reason=reason, ms=ms)
            doubt = None
        if doubt is None:
            log_event("no_doubt", reason=reason, ms=ms)
            if asked:
                await self.send({"type": "doubt", "id": uuid4().hex[:8], "question": None,
                                 "why": "Nothing new to ask in your topics right now.", "sources": [], "reason": reason})
            return
        self.doubts.append(doubt.question)
        self.doubt_at_s = self.audio_now_s()
        payload = {"type": "doubt", "id": uuid4().hex[:8], "question": doubt.question, "why": doubt.why, "reason": reason,
                   "sources": [{"number": s.number, "document": s.document, "location": s.location, "text": s.text} for s in doubt.sources]}
        log_event("doubt", question=doubt.question, reason=reason, closest=round(closest, 3), ms=ms,
                  sources=[f"{s.document}, {s.location}" for s in doubt.sources])
        await self.send(payload)
        if self.record:
            await self.store.add_item(SessionItem(
                session_id=self.record.session_id,
                timestamp=self.record.started_at * 1000 + int(self.audio_now_s() * 1000),
                type="doubt", payload={k: v for k, v in payload.items() if k != "type"}, ttl=self.expires_at(),
            ))

    # Notes agent

    def _unnoted_turns(self) -> list[Turn]:
        return [t for t in self.turns.turns if t.end_s > self.notes_through_s and not t.echo]

    def _maybe_update_notes(self) -> None:
        """Every NOTES_EVERY_S of audio, when something new was said and no card is being written."""
        due = self.audio_now_s() - self.notes_at_s >= settings.notes_every_s
        if due and not self.noting and not self.answering and self._unnoted_turns():
            self.noting = asyncio.create_task(self._update_notes())
            self.noting.add_done_callback(lambda t: setattr(self, "noting", None))

    async def _update_notes(self) -> None:
        assert self.profile
        new_turns = self._unnoted_turns()
        through = max(t.end_s for t in new_turns)
        started = time.perf_counter()
        try:
            self.notes = await self.notes_agent.update(self.profile, self.notes, new_turns)
        except asyncio.CancelledError:
            return   # an answer took the GPU; the next tick retries
        except Exception as error:
            log_event("notes_failed", error=str(error))
            return
        self.notes_through_s, self.notes_at_s = through, self.audio_now_s()
        log_event("notes", bullets=len(self.notes), turns=len(new_turns), ms=int((time.perf_counter() - started) * 1000))
        await self.send({"type": "notes_update", "notes": self.notes})
        if self.record:
            await self.store.add_item(SessionItem(
                session_id=self.record.session_id,
                timestamp=self.record.started_at * 1000 + int(self.audio_now_s() * 1000),
                type="notes", payload={"notes": self.notes}, ttl=self.expires_at(),
            ))

    async def _remember_turn(self, turn: Turn) -> None:
        """Final turns are the meeting's memory: stored as session items, text only, and they expire."""
        assert self.record
        await self.store.add_item(SessionItem(
            session_id=self.record.session_id,
            timestamp=self.record.started_at * 1000 + int(turn.end_s * 1000),
            type="final_turn",
            payload={"channel": turn.channel, "text": turn.text, "start_s": turn.start_s, "end_s": turn.end_s, "echo": turn.echo},
            ttl=self.expires_at(),
        ))
