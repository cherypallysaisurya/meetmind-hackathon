import { useEffect, useRef, useState } from "react";
import { createAudioSource, type AudioSource, type Frame } from "../audio/AudioSource";
import { editPreparedCard, rehearseCard, type PreparedCardRecord, type PreparedMeeting, type Rehearsal } from "../session/api";

type Props = { meeting: PreparedMeeting; cards: PreparedCardRecord[]; onBack: () => void };
type Step = "asking" | "recording" | "checking" | "result";

const FRAME_BYTES = 6400;   // 100 ms of 16 kHz stereo 16-bit audio, as the service expects

function speak(text: string): void {
  speechSynthesis.cancel();
  speechSynthesis.speak(new SpeechSynthesisUtterance(text));
}

function joined(frames: Frame[]): Uint8Array<ArrayBuffer> {
  const bytes = new Uint8Array(frames.length * FRAME_BYTES);
  frames.forEach((frame, i) => bytes.set(new Uint8Array(frame.buffer), i * FRAME_BYTES));
  return bytes;
}

function messageOf(failure: unknown): string {
  return failure instanceof Error ? failure.message : String(failure);
}

// Rehearsal before the meeting (decision 0009): each prepared question is read out loud, the user answers, and the
// answer comes back checked against their documents and as a card in their own words, which they can keep.
export function RehearseScreen({ meeting, cards, onBack }: Props) {
  const [index, setIndex] = useState(0);
  const [step, setStep] = useState<Step>("asking");
  const [result, setResult] = useState<Rehearsal | null>(null);
  const [kept, setKept] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const source = useRef<AudioSource | null>(null);
  const frames = useRef<Frame[]>([]);
  const card = cards[index];

  useEffect(() => {
    setStep("asking");
    setResult(null);
    setError(null);
    speak(card.question);
  }, [index]);

  useEffect(() => () => { speechSynthesis.cancel(); source.current?.stop(); }, []);

  async function record() {
    speechSynthesis.cancel();
    frames.current = [];
    setError(null);
    source.current = createAudioSource();
    try {
      await source.current.start((frame) => frames.current.push(frame), false);
      setStep("recording");
    } catch (failure) {
      setError(`Could not use the microphone: ${messageOf(failure)}`);
    }
  }

  async function finish() {
    source.current?.stop();
    source.current = null;
    setStep("checking");
    try {
      setResult(await rehearseCard(meeting.sessionId, card.cardId, joined(frames.current)));
      setStep("result");
    } catch (failure) {
      setError(messageOf(failure));
      setStep("asking");
    }
  }

  async function keep() {
    if (!result) return;
    await editPreparedCard(meeting.sessionId, card.cardId, result.line, result.points);
    setKept([...kept, card.cardId]);
  }

  const check = result?.check;
  return (
    <div className="screen rehearse">
      <div className="row">
        <button type="button" className="link" onClick={onBack}>Back</button>
        <strong className="grow">Rehearse: {meeting.title}</strong>
        <span className="muted">{index + 1} of {cards.length}</span>
      </div>
      <p className="rehearse-question" data-field="rehearse-question">{card.question}</p>

      {step === "asking" && (
        <div className="row">
          <button type="button" className="primary" data-action="answer" onClick={record}>Answer out loud</button>
          <button type="button" className="link" onClick={() => speak(card.question)}>Read it again</button>
        </div>
      )}
      {step === "recording" && (
        <div className="row">
          <span className="state"><span className="dot live" /> Listening to your answer</span>
          <button type="button" className="primary" data-action="done" onClick={finish}>Done</button>
        </div>
      )}
      {step === "checking" && <p className="muted">Checking your answer against your documents</p>}
      {error && <p className="error">{error}</p>}

      {step === "result" && result && check && (
        <>
          <p className="muted">You said: {result.heard}</p>
          {check.verdict === "contradicts" && (
            <div className="check contradicts" data-field="check">
              <strong>Your docs say otherwise</strong>
              <p className="quote">{check.quote}</p>
              <p className="muted">{check.document}, {check.location}</p>
              <p>Closer to your docs: {check.line}</p>
            </div>
          )}
          {check.verdict === "supports" && (
            <div className="check supports" data-field="check">
              <strong>Matches your docs</strong>
              <p className="quote">{check.quote}</p>
              <p className="muted">{check.document}, {check.location}</p>
            </div>
          )}
          {check.verdict === "not_found" && (
            <div className="check" data-field="check">Your docs do not cover this. Fine if it is your own view.</div>
          )}
          <div className="prepared-card">
            <div className="prepared-question">Your answer as the card</div>
            <p className="prepared-line">{result.line}</p>
            <ul className="cue-points">{result.points.map((point, i) => <li key={i}>{point}</li>)}</ul>
          </div>
          <div className="row">
            {kept.includes(card.cardId)
              ? <span className="chip label">Kept as the card</span>
              : <button type="button" data-action="keep" onClick={keep}>{check.verdict === "contradicts" ? "Keep my words anyway" : "Keep my words as the card"}</button>}
            <button type="button" className="link" onClick={() => setStep("asking")}>Try again</button>
          </div>
        </>
      )}

      <div className="row">
        <button type="button" className="link" disabled={index === 0 || step === "recording" || step === "checking"} onClick={() => setIndex(index - 1)}>Previous</button>
        <span className="grow" />
        <button type="button" className="link" data-action="next-question" disabled={index === cards.length - 1 || step === "recording" || step === "checking"}
          onClick={() => setIndex(index + 1)}>{step === "result" ? "Next question" : "Skip"}</button>
      </div>
    </div>
  );
}
