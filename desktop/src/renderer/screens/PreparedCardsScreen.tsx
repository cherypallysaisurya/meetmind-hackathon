import { useEffect, useRef, useState } from "react";
import {
  addPreparedCard, buildPrepared, deletePreparedCard, editPreparedCard, getPreparedCards, getPrepStatus,
  type PreparedCardRecord, type PreparedMeeting, type PrepStatus,
} from "../session/api";
import { RehearseScreen } from "./RehearseScreen";

type Props = { meeting: PreparedMeeting; onBack: () => void };

const POLL_MS = 1500;

function describe(status: PrepStatus): string {
  if (status.state === "predicting") return "Predicting the questions you are likely to get";
  if (status.state === "writing") return `Writing card ${Math.min(status.done + 1, status.total)} of ${status.total} (${Math.round(status.seconds)} s)`;
  if (status.state === "done") return `Prepared ${status.done} cards in ${Math.round(status.seconds)} s`;
  if (status.state === "failed") return `Preparing failed: ${status.error}`;
  return "";
}

// The prepared cards of one meeting: build them, read them, fix them. An edited card counts as approved.
export function PreparedCardsScreen({ meeting, onBack }: Props) {
  const [cards, setCards] = useState<PreparedCardRecord[]>([]);
  const [status, setStatus] = useState<PrepStatus | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState({ line: "", points: "" });
  const [question, setQuestion] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rehearsing, setRehearsing] = useState(false);
  const timer = useRef<number | null>(null);
  const building = status?.state === "predicting" || status?.state === "writing";

  async function refresh() {
    try {
      setCards(await getPreparedCards(meeting.sessionId));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  }

  async function poll() {
    const latest = await getPrepStatus(meeting.sessionId);
    setStatus(latest);
    if (latest.state === "predicting" || latest.state === "writing") {
      timer.current = window.setTimeout(poll, POLL_MS);
    } else {
      await refresh();
    }
  }

  useEffect(() => {
    refresh();
    poll();   // a build started earlier may still be running
    return () => { if (timer.current) window.clearTimeout(timer.current); };
  }, [meeting.sessionId]);

  async function build() {
    setError(null);
    setStatus(await buildPrepared(meeting.sessionId));
    timer.current = window.setTimeout(poll, POLL_MS);
  }

  function edit(card: PreparedCardRecord) {
    setEditing(card.cardId);
    setDraft({ line: card.card.line ?? "", points: card.card.points.map((p) => p.text).join("\n") });
  }

  async function save(card: PreparedCardRecord) {
    await editPreparedCard(meeting.sessionId, card.cardId, draft.line, draft.points.split("\n"));
    setEditing(null);
    await refresh();
  }

  async function remove(card: PreparedCardRecord) {
    await deletePreparedCard(meeting.sessionId, card.cardId);
    await refresh();
  }

  async function add(event: React.FormEvent) {
    event.preventDefault();
    if (!question.trim()) return;
    setAdding(true);
    try {
      await addPreparedCard(meeting.sessionId, question.trim());
      setQuestion("");
      await refresh();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
    setAdding(false);
  }

  if (rehearsing) return <RehearseScreen meeting={meeting} cards={cards} onBack={() => { setRehearsing(false); refresh(); }} />;

  return (
    <div className="screen">
      <div className="row">
        <button type="button" className="link" onClick={onBack}>Back</button>
        <strong className="grow">{meeting.title}</strong>
        {cards.length > 0 && !building && (
          <button type="button" data-action="rehearse" onClick={() => setRehearsing(true)} title="The questions are read out loud; you answer; your answer is checked against your documents">
            Rehearse
          </button>
        )}
      </div>
      <div className="row">
        <button type="button" className="primary" data-action="build" onClick={build} disabled={building}>
          {cards.length ? "Prepare again" : "Prepare cards"}
        </button>
        <span className="muted">{cards.length ? "Your edited cards are kept." : "Takes a few minutes; you can keep working."}</span>
      </div>
      {status && status.state !== "idle" && (
        <div className="prep-status" data-field="prep-status">
          {building && <span className="progress"><span style={{ width: `${status.total ? (100 * status.done) / status.total : 5}%` }} /></span>}
          <span className={status.state === "failed" ? "error" : "muted"}>{describe(status)}</span>
        </div>
      )}
      {error && <p className="error">{error}</p>}

      <form className="row" onSubmit={add}>
        <input id="prep-question" className="grow" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Add a question you expect" disabled={adding} />
        <button type="submit" disabled={adding || !question.trim()}>{adding ? "Writing" : "Add"}</button>
      </form>

      <ul className="prepared-cards" data-field="prepared-cards">
        {cards.length === 0 && !building && <li className="muted">No prepared cards yet.</li>}
        {cards.map((card) => (
          <li key={card.cardId} className="prepared-card">
            <div className="prepared-question">{card.question}{card.userEdited && <span className="chip label">Edited by you</span>}</div>
            {editing === card.cardId ? (
              <>
                <input value={draft.line} onChange={(e) => setDraft({ ...draft, line: e.target.value })} placeholder="The line to say" />
                <textarea rows={4} value={draft.points} onChange={(e) => setDraft({ ...draft, points: e.target.value })} placeholder="One point per line" />
                <div className="row">
                  <button type="button" onClick={() => save(card)}>Save</button>
                  <button type="button" className="link" onClick={() => setEditing(null)}>Cancel</button>
                </div>
              </>
            ) : (
              <>
                <p className="prepared-line">
                  {card.card.line ?? (card.card.tags.asks_to_agree ? "Your call: no line, answer from what you know" : "No line (low confidence), points only")}
                </p>
                <ul className="cue-points">
                  {card.card.points.map((point, index) => (
                    <li key={index}>{point.text}{point.sources.map((n) => <sup key={n} className="source-ref">{n}</sup>)}</li>
                  ))}
                </ul>
                <div className="cue-footer">
                  {card.card.confidence && <span className={`chip confidence ${card.card.confidence}`}>{card.card.confidence} confidence</span>}
                  {card.sources.map((s) => <span key={s.number} className="chip source" title={`${s.location}: ${s.text}`}>{s.number} {s.document}</span>)}
                </div>
                <div className="row">
                  <button type="button" className="link" onClick={() => edit(card)}>Edit</button>
                  <button type="button" className="link" onClick={() => remove(card)}>Delete</button>
                </div>
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
