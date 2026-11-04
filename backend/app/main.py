"""The MeetMind service: one FastAPI process with the health check, the profile routes, the WebSocket
route and, from Phase 2P, the /api routes for preparation.

Run from the backend folder:
    .venv/bin/python -m app.main
It listens on localhost only (BACKEND_HOST and BACKEND_PORT in .env).
"""

import asyncio
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from uvicorn.protocols.utils import ClientDisconnected

from .adapters.factory import (make_auth, make_document_parser, make_embeddings, make_llm, make_speech_to_text,
                               make_store, make_vector_store)
from .audio.frames import FRAME_BYTES
from .audio.replay import replay_files
from .config import settings
from uuid import uuid4

from .agents.answer import AnswerAgent
from .ports import Document, Message, PrepCard, Profile, Session as SessionRecord, User
from .prep.cache import AnswerCache, PrepProgress
from .prep.documents import Documents
from .prep.predictor import QuestionPredictor
from .prep.rehearsal import Rehearsal, transcribe
from .session.orchestrator import Session, make_claim_checker
from .telemetry.log import configure as configure_logging
from .telemetry.log import log_event

configure_logging()
auth = make_auth()
store = make_store()
llm = make_llm()
embeddings = make_embeddings()
vectors = make_vector_store()
documents = Documents(make_document_parser(), embeddings, vectors, store)


async def warm_up_models() -> None:
    """Load the classifier, the answer model and the embedding model now, so the first question of a
    meeting does not pay for a cold load (several seconds each, see Step 0.2)."""
    started = time.perf_counter()
    try:
        await embeddings.embed(["warm up"])
        async for _ in llm.stream(settings.llm_answer_model, [Message("user", "Say ok.")]):
            break
        await llm.complete_json(settings.llm_classifier_model, [Message("user", "Reply with {\"ok\": true}")],
                                {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]})
        log_event("models_warm", seconds=round(time.perf_counter() - started, 1))
    except Exception as error:   # the service still runs; the first question will just be slower
        log_event("warm_up_failed", error=str(error))
    user = await auth.authenticate(None)   # the one user of local mode; nobody before sign-in otherwise
    if user:
        await prime_claim_checker(user.user_id)


async def prime_claim_checker(user_id: str) -> None:
    """Read the user's documents into the model's prompt cache, so the first claim check of the next meeting is
    not the slow one (about 35 s on the local model, then 3 to 6 s, decision 0009)."""
    checker = make_claim_checker(llm, embeddings, vectors)
    if not checker:
        return
    started = time.perf_counter()
    try:
        await checker.prime(user_id)
        log_event("claim_checker_primed", ms=int((time.perf_counter() - started) * 1000))
    except Exception as error:
        log_event("prime_failed", error=str(error))


claim_priming: asyncio.Task | None = None


def prime_in_background(user_id: str) -> None:
    """After documents change and after a meeting; a newer start cancels the older read, so six uploads cost one."""
    stop_priming()
    global claim_priming
    claim_priming = asyncio.create_task(prime_claim_checker(user_id))


def stop_priming() -> None:
    """A meeting is starting: its cards come first. On the local model a first read holds the GPU for 35 s or more."""
    if claim_priming and not claim_priming.done():
        claim_priming.cancel()
        log_event("claim_priming_stopped")


@asynccontextmanager
async def lifespan(_: FastAPI):
    warming = asyncio.create_task(warm_up_models())
    yield
    warming.cancel()


app = FastAPI(title="MeetMind service", lifespan=lifespan)


def bearer_token(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:]
    return None


async def current_user(authorization: str | None = Header(default=None)) -> User:
    user = await auth.authenticate(bearer_token(authorization))
    if user is None:
        raise HTTPException(status_code=401, detail="not signed in")
    return user


@app.get("/api/health")
def health():
    """The auth mode, and where the language model runs, so the app can tell the user (and the meeting) the truth."""
    return {"status": "ok", "mode": auth.mode, "llm": settings.llm_provider, "answerModel": settings.llm_answer_model}


# The profile as the desktop sends and receives it: the data model's field names.
class ProfileBody(BaseModel):
    displayName: str = Field(min_length=1)
    aliases: list[str] = []
    role: str = ""
    topics: list[str] = []
    bio: str = Field("", max_length=2000)
    currentProjects: str = Field("", max_length=4000)


def profile_json(profile: Profile) -> dict:
    return {
        "displayName": profile.display_name, "aliases": profile.aliases, "role": profile.role,
        "topics": profile.topics, "bio": profile.bio, "currentProjects": profile.current_projects,
    }


@app.get("/api/profile")
async def get_profile(user: User = Depends(current_user)):
    profile = await store.get_profile(user.user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="no profile saved yet")
    return profile_json(profile)


@app.put("/api/profile")
async def put_profile(body: ProfileBody, user: User = Depends(current_user)):
    existing = await store.get_profile(user.user_id)
    profile = Profile(
        user_id=user.user_id, display_name=body.displayName, aliases=body.aliases, role=body.role,
        topics=body.topics, bio=body.bio, current_projects=body.currentProjects,
        created_at=existing.created_at if existing else int(time.time()),
    )
    await store.save_profile(profile)
    return profile_json(profile)


def document_json(document: Document) -> dict:
    return {"docId": document.doc_id, "name": document.name, "type": document.type, "addedAt": document.added_at,
            "chunkCount": document.chunk_count, "status": document.status}


@app.get("/api/documents")
async def list_documents(user: User = Depends(current_user)):
    return {"documents": [document_json(d) for d in await documents.list(user.user_id)]}


@app.post("/api/documents")
async def upload_document(file: UploadFile, user: User = Depends(current_user)):
    name = file.filename or "document"
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if extension not in documents.parser.supported_types():
        raise HTTPException(status_code=415, detail=f"{name}: use pdf, md, txt or docx")
    data = await file.read()
    if len(data) > settings.max_document_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"{name} is over {settings.max_document_mb} MB")
    try:
        added = await documents.add(user.user_id, name, data)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    prime_in_background(user.user_id)
    return document_json(added)


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str, user: User = Depends(current_user)):
    await documents.remove(user.user_id, doc_id)
    prime_in_background(user.user_id)
    return {"deleted": doc_id}


class PrepBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    agenda: str = Field(min_length=1, max_length=8000)
    participants: list[str] = []


def prep_json(record: SessionRecord) -> dict:
    return {"sessionId": record.session_id, "title": record.title, "agenda": record.agenda,
            "participants": record.participants, "held": record.started_at > 0}


async def prepared_meeting(user: User, session_id: str) -> SessionRecord:
    record = await store.get_session(user.user_id, session_id)
    if record is None or not record.agenda:
        raise HTTPException(status_code=404, detail="no prepared meeting with that id")
    return record


@app.get("/api/prep")
async def list_prepared(user: User = Depends(current_user)):
    """Meetings prepared ahead of time, the ones not held yet first."""
    records = [s for s in await store.list_sessions(user.user_id) if s.agenda]
    return {"meetings": [prep_json(s) for s in sorted(records, key=lambda s: (s.started_at > 0, -s.started_at))]}


@app.post("/api/prep")
async def create_prepared(body: PrepBody, user: User = Depends(current_user)):
    record = SessionRecord(
        user_id=user.user_id, session_id=uuid4().hex, title=body.title.strip(), started_at=0, ended_at=None,
        summary="", todos=[], ttl=int(time.time()) + settings.retention_days * 86400,
        agenda=body.agenda.strip(), participants=[p.strip() for p in body.participants if p.strip()],
    )
    await store.save_session(record)
    return prep_json(record)


@app.put("/api/prep/{session_id}")
async def update_prepared(session_id: str, body: PrepBody, user: User = Depends(current_user)):
    record = await prepared_meeting(user, session_id)
    record.title, record.agenda = body.title.strip(), body.agenda.strip()
    record.participants = [p.strip() for p in body.participants if p.strip()]
    await store.save_session(record)
    return prep_json(record)


@app.delete("/api/prep/{session_id}")
async def delete_prepared(session_id: str, user: User = Depends(current_user)):
    await prepared_meeting(user, session_id)
    await answer_cache().forget(session_id)
    await store.delete_session(user.user_id, session_id)
    prep_jobs.pop(session_id, None)
    return {"deleted": session_id}


# Prepared cards (step P.3). Building runs in the background; the Prepare tab polls its progress.

prep_jobs: dict[str, PrepProgress] = {}
running_builds: set[asyncio.Task] = set()   # a reference keeps a running build from being garbage collected


def answer_cache() -> AnswerCache:
    agent = AnswerAgent(llm, embeddings, vectors, settings.llm_answer_model, settings.retrieval_top_k, settings.retrieval_min_score,
                        make_claim_checker(llm, embeddings, vectors))
    return AnswerCache(store, embeddings, vectors, agent, QuestionPredictor(llm, embeddings, vectors, settings.llm_answer_model))


async def saved_profile(user: User) -> Profile:
    profile = await store.get_profile(user.user_id)
    if profile is None:
        raise HTTPException(status_code=409, detail="fill in the Profile screen first")
    return profile


def progress_json(progress: PrepProgress) -> dict:
    return {"state": progress.state, "done": progress.done, "total": progress.total, "seconds": progress.seconds, "error": progress.error}


def card_json(card: PrepCard) -> dict:
    return {"cardId": card.card_id, "question": card.predicted_question, "variants": card.variants, "card": card.card,
            "sources": card.sources, "userEdited": card.user_edited}


async def prepared_card(meeting: SessionRecord, card_id: str) -> PrepCard:
    for card in await store.list_prep_cards(meeting.session_id):
        if card.card_id == card_id:
            return card
    raise HTTPException(status_code=404, detail="no prepared card with that id")


@app.post("/api/prep/{session_id}/build")
async def build_prepared(session_id: str, user: User = Depends(current_user)):
    meeting = await prepared_meeting(user, session_id)
    profile = await saved_profile(user)
    current = prep_jobs.get(session_id)
    if current and current.state in ("predicting", "writing"):
        return progress_json(current)
    progress = prep_jobs[session_id] = PrepProgress(state="predicting")

    async def run() -> None:
        try:
            await answer_cache().build(profile, meeting, progress)
            log_event("prep_built", session_id=session_id, cards=progress.done, seconds=progress.seconds)
        except Exception as error:
            progress.state, progress.error = "failed", str(error)
            log_event("prep_failed", session_id=session_id, error=str(error))

    task = asyncio.create_task(run())
    running_builds.add(task)
    task.add_done_callback(running_builds.discard)
    return progress_json(progress)


@app.get("/api/prep/{session_id}/status")
async def prepared_status(session_id: str, user: User = Depends(current_user)):
    await prepared_meeting(user, session_id)
    return progress_json(prep_jobs.get(session_id, PrepProgress()))


@app.get("/api/prep/{session_id}/cards")
async def list_prepared_cards(session_id: str, user: User = Depends(current_user)):
    meeting = await prepared_meeting(user, session_id)
    cards = sorted(await store.list_prep_cards(meeting.session_id), key=lambda c: (not c.user_edited, c.created_at))
    return {"cards": [card_json(c) for c in cards]}


class QuestionBody(BaseModel):
    question: str = Field(min_length=1, max_length=500)


@app.post("/api/prep/{session_id}/cards")
async def add_prepared_card(session_id: str, body: QuestionBody, user: User = Depends(current_user)):
    """A question the user expects that the predictor missed: the card is written now."""
    meeting = await prepared_meeting(user, session_id)
    return card_json(await answer_cache().add(await saved_profile(user), meeting, body.question.strip()))


class CardEditBody(BaseModel):
    line: str = Field("", max_length=300)
    points: list[str] = []


@app.put("/api/prep/{session_id}/cards/{card_id}")
async def edit_prepared_card(session_id: str, card_id: str, body: CardEditBody, user: User = Depends(current_user)):
    meeting = await prepared_meeting(user, session_id)
    return card_json(await answer_cache().edit(await prepared_card(meeting, card_id), body.line, body.points))


@app.delete("/api/prep/{session_id}/cards/{card_id}")
async def delete_prepared_card(session_id: str, card_id: str, user: User = Depends(current_user)):
    meeting = await prepared_meeting(user, session_id)
    await answer_cache().remove(await prepared_card(meeting, card_id))
    return {"deleted": card_id}


MAX_REHEARSAL_FRAMES = 1200   # two minutes of answer


@app.post("/api/prep/{session_id}/cards/{card_id}/rehearse")
async def rehearse_card(session_id: str, card_id: str, request: Request, user: User = Depends(current_user)):
    """The user's spoken answer to a prepared question, as raw frames (decision 0009): what was heard, the answer as a
    card in their own words, and what their documents say about it. Nothing is saved; keeping the card is an edit."""
    meeting = await prepared_meeting(user, session_id)
    card = await prepared_card(meeting, card_id)
    audio = await request.body()
    if len(audio) < 10 * FRAME_BYTES:
        raise HTTPException(status_code=422, detail="the recording is shorter than a second")
    if len(audio) > MAX_REHEARSAL_FRAMES * FRAME_BYTES:
        raise HTTPException(status_code=413, detail="the recording is longer than two minutes")
    heard = await transcribe(make_speech_to_text(), audio)
    if not heard:
        raise HTTPException(status_code=422, detail="no speech was heard in the recording")
    rehearsal = Rehearsal(llm, settings.llm_answer_model, make_claim_checker(llm, embeddings, vectors))
    result = await rehearsal.review(user.user_id, await saved_profile(user), card.predicted_question, heard)
    log_event("rehearsed", session_id=session_id, card_id=card_id, words=len(heard.split()), verdict=result.check.verdict)
    check = result.check
    return {"heard": result.heard, "line": result.line, "points": result.points,
            "check": {"verdict": check.verdict, "line": check.line, "quote": check.quote, "document": check.document, "location": check.location}}


@app.get("/api/replays")
async def list_replays(user: User = Depends(current_user)):
    """Test meetings available to replay mode, by file name."""
    return {"files": replay_files(settings.path("replay_dir"))}


@app.websocket("/ws")
async def websocket_session(websocket: WebSocket, token: str | None = None):
    user = await auth.authenticate(token)
    if user is None:
        await websocket.close(code=4401, reason="not signed in")
        return
    await websocket.accept()
    stop_priming()

    async def send_if_connected(event: dict) -> None:
        try:
            await websocket.send_json(event)
        except (WebSocketDisconnect, ClientDisconnected, RuntimeError):
            pass   # the client left; there is nobody to tell

    session = Session(send=send_if_connected, make_stt=make_speech_to_text, store=store, llm=llm, embeddings=embeddings,
                      vectors=vectors, user=user, retention_days=settings.retention_days)
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                await session.handle_frame(message["bytes"])
            elif message.get("text") is not None:
                await session.handle_text(message["text"])
    except WebSocketDisconnect:
        pass
    finally:
        await session.close()
        prime_in_background(user.user_id)   # ready for the next meeting


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.backend_host, port=settings.backend_port, reload=True)
