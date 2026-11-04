import { useRef, useState } from "react";
import { createAudioSource, type AudioSource } from "./audio/AudioSource";
import { levelsOf, type Levels } from "./audio/levels";
import { SERVICE_WS_URL } from "./config";
import { meetingMarkdown } from "./export";
import { ServiceConnection, type AlertEvent, type CardBody, type CardSource, type Channel, type ConnectionStatus, type DoubtEvent, type LatencyEvent, type ServerEvent, type TranscriptEvent, type TurnEvent } from "./session/ServiceConnection";

// An alert card plus whatever the answer agent has written for it so far.
export type Answer = { card: CardBody; sources: CardSource[]; done: boolean; label: "live" | "prepared" | null };
export type AlertCardState = AlertEvent & { answer: Answer | null };

export type SessionState = "idle" | "starting" | "listening" | "replaying" | "stopping";

export type Partials = Partial<Record<Channel, string>>;

const RETRACTED_CARD_STAYS_MS = 6000;   // a card shown and then retracted fades out after this long

// The one-on-one and documents switches are remembered on this Mac between launches.
function rememberedOneOnOne(): boolean {
  try { return localStorage.getItem("one-on-one") === "yes"; } catch { return false; }
}

function rememberedUseDocuments(): boolean {
  try { return localStorage.getItem("use-documents") !== "no"; } catch { return true; }
}

function rememberedSeeScreen(): boolean {
  try { return localStorage.getItem("see-screen") === "yes"; } catch { return false; }
}

export type ChosenMeeting = { sessionId: string; title: string };

function rememberedMeeting(): ChosenMeeting | null {
  try { return JSON.parse(localStorage.getItem("prepared-meeting") ?? "null"); } catch { return null; }
}

// A meeting session as the UI sees it: the connection to the service plus the audio source.
// Start opens the connection, sends the profile, then starts the audio and streams every frame.
export function useSession() {
  const source = useRef<AudioSource | null>(null);
  const connection = useRef<ServiceConnection | null>(null);
  const [state, setState] = useState<SessionState>("idle");
  const [levels, setLevels] = useState<Levels>({ me: -Infinity, them: -Infinity });
  const [framesSent, setFramesSent] = useState(0);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("closed");
  const [lastEvent, setLastEvent] = useState<ServerEvent | null>(null);
  const [lines, setLines] = useState<TranscriptEvent[]>([]);       // final transcripts, oldest first
  const [partials, setPartials] = useState<Partials>({});           // what each channel is saying right now
  const [lastTurn, setLastTurn] = useState<TurnEvent | null>(null);
  const [alerts, setAlerts] = useState<AlertCardState[]>([]);   // open cards, the first one is shown
  const [latencies, setLatencies] = useState<LatencyEvent[]>([]);
  const [notes, setNotes] = useState<string[]>([]);               // the meeting's running notes, rewritten every minute or so
  const [doubt, setDoubt] = useState<DoubtEvent | null>(null);    // the latest question the user could ask
  const [askingDoubt, setAskingDoubt] = useState(false);          // the user pressed Suggest a question and waits for it
  const doubts = useRef<string[]>([]);                            // every question suggested this meeting, for the export
  const [error, setError] = useState<string | null>(null);
  const [oneOnOne, setOneOnOneState] = useState(rememberedOneOnOne);   // a meeting of two: every question from them is for the user
  const [useDocuments, setUseDocumentsState] = useState(rememberedUseDocuments);   // off: answers from the model alone
  const [seeScreen, setSeeScreenState] = useState(rememberedSeeScreen);             // on: a question about "this chart" gets a picture of the screen
  const [chosenMeeting, setChosenMeetingState] = useState(rememberedMeeting);       // the prepared meeting the next start uses
  const seen = useRef(new Map<string, AlertCardState>());         // every card of the session, dismissed ones too, for the export
  const startedAt = useRef(new Date());

  function onEvent(event: ServerEvent) {
    if (event.type === "transcript") {
      if (event.is_partial) {
        setPartials((current) => ({ ...current, [event.channel]: event.text }));
      } else {
        setLines((current) => [...current, event]);
        setPartials((current) => ({ ...current, [event.channel]: undefined }));
      }
      return;
    }
    if (event.type === "turn") {
      setLastTurn(event);
      return;
    }
    if (event.type === "notes_update") {
      setNotes(event.notes);
      return;
    }
    if (event.type === "doubt") {
      setDoubt(event);
      setAskingDoubt(false);
      if (event.question) doubts.current.push(event.question);
      return;
    }
    if (event.type === "screen_request") {
      window.meetmind.captureScreen()
        .catch(() => null)
        .then((jpeg) => connection.current?.send({ type: "screen", alert_id: event.alert_id, jpeg }));
      return;
    }
    if (event.type === "latency") {
      // The same question reports twice (after the classifier, after the card); keep the latest.
      setLatencies((current) => current.some((l) => l.alert_id === event.alert_id)
        ? current.map((l) => (l.alert_id === event.alert_id ? event : l)) : [...current, event]);
      return;
    }
    if (event.type === "alert") {
      seen.current.set(event.id, { ...event, answer: seen.current.get(event.id)?.answer ?? null });
      // Retracted: the classifier says it was not for the user. A card with nothing written yet goes away;
      // a card whose cue line is already on screen stays, tagged, because the user may be reading it.
      // Same id: an update to a card already shown. New id: a new card at the end of the queue.
      setAlerts((current) => {
        const existing = current.find((a) => a.id === event.id);
        if (event.status === "retracted") {
          if (!existing?.answer?.card.line) return current.filter((a) => a.id !== event.id);
          // The cue line is on screen, so it stays readable for a moment, tagged, then goes.
          setTimeout(() => setAlerts((later) => later.filter((a) => a.id !== event.id)), RETRACTED_CARD_STAYS_MS);
          return current.map((a) => (a.id === event.id ? { ...event, answer: a.answer } : a));
        }
        return existing
          ? current.map((a) => (a.id === event.id ? { ...event, answer: a.answer } : a))
          : [...current, { ...event, answer: null }];
      });
      return;
    }
    if (event.type === "answer_delta" || event.type === "answer_done") {
      const known = seen.current.get(event.alert_id);
      if (known) {
        seen.current.set(event.alert_id, { ...known, answer: event.type === "answer_done"
          ? { card: event.card, sources: event.sources, done: true, label: event.label }
          : { card: event.card, sources: known.answer?.sources ?? [], done: false, label: known.answer?.label ?? null } });
      }
      setAlerts((current) => current.map((a) => a.id !== event.alert_id ? a : {
        ...a,
        answer: event.type === "answer_done"
          ? { card: event.card, sources: event.sources, done: true, label: event.label }
          : { card: event.card, sources: a.answer?.sources ?? [], done: false, label: a.answer?.label ?? null },
      }));
      return;
    }
    setLastEvent(event);
    if (event.type === "error") { setError(`service: ${event.message}`); setAskingDoubt(false); }
    if (event.type === "stopped") setState((current) => (current === "replaying" ? "idle" : current));
  }

  // Live: open the connection, then the mic and system audio. Replay: the service plays a test meeting instead.
  async function start(replayFile?: string) {
    setState("starting");
    setError(null);
    setFramesSent(0);
    setLastEvent(null);
    setLines([]);
    setPartials({});
    setLastTurn(null);
    setAlerts([]);
    setLatencies([]);
    setNotes([]);
    setDoubt(null);
    doubts.current = [];
    seen.current = new Map();
    startedAt.current = new Date();
    connection.current = new ServiceConnection(SERVICE_WS_URL, onEvent, setConnectionStatus);
    try {
      await connection.current.open(replayFile, replayFile ? undefined : chosenMeeting?.sessionId);
      if (oneOnOne) connection.current.send({ type: "one_on_one", on: true });
      if (!useDocuments) connection.current.send({ type: "use_documents", on: false });
      if (seeScreen) connection.current.send({ type: "see_screen", on: true });
      if (replayFile) {
        setState("replaying");
        return;
      }
      source.current = createAudioSource();
      await source.current.start((frame) => {
        connection.current?.sendFrame(frame);
        setLevels(levelsOf(frame));
        setFramesSent((count) => count + 1);
      });
      setState("listening");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
      stop();
    }
  }

  async function stop() {
    setState("stopping");
    source.current?.stop();
    source.current = null;
    setLevels({ me: -Infinity, them: -Infinity });
    await connection.current?.close();   // the last transcripts arrive while we wait
    connection.current = null;
    setState("idle");
  }

  function attention() {
    connection.current?.send({ type: "attention" });
  }

  function suggestQuestion() {
    if (!connection.current) return;
    setAskingDoubt(true);
    connection.current.send({ type: "doubt" });
  }

  function setOneOnOne(on: boolean) {
    setOneOnOneState(on);
    try { localStorage.setItem("one-on-one", on ? "yes" : "no"); } catch { /* private window or blocked storage: the switch just will not be remembered */ }
    connection.current?.send({ type: "one_on_one", on });
  }

  function chooseMeeting(meeting: ChosenMeeting | null) {
    const chosen = meeting && { sessionId: meeting.sessionId, title: meeting.title };
    setChosenMeetingState(chosen);
    try { localStorage.setItem("prepared-meeting", JSON.stringify(chosen)); } catch { /* not remembered across launches */ }
  }

  function setUseDocuments(on: boolean) {
    setUseDocumentsState(on);
    try { localStorage.setItem("use-documents", on ? "yes" : "no"); } catch { /* the switch just will not be remembered */ }
    connection.current?.send({ type: "use_documents", on });
  }

  function setSeeScreen(on: boolean) {
    setSeeScreenState(on);
    try { localStorage.setItem("see-screen", on ? "yes" : "no"); } catch { /* the switch just will not be remembered */ }
    connection.current?.send({ type: "see_screen", on });
  }

  // Notes, every card and the conversation, as one Markdown file the user saves where they like.
  async function exportMeeting(): Promise<string | null> {
    const stamp = startedAt.current;
    const pad = (n: number) => String(n).padStart(2, "0");
    const name = `meetmind-${stamp.getFullYear()}-${pad(stamp.getMonth() + 1)}-${pad(stamp.getDate())}-${pad(stamp.getHours())}${pad(stamp.getMinutes())}.md`;
    return window.meetmind.saveFile(name, meetingMarkdown(stamp, notes, [...seen.current.values()], doubts.current, lines));
  }

  function dismissCard() {
    setAlerts((current) => current.slice(1));
  }

  function nextCard() {
    setAlerts((current) => (current.length > 1 ? [...current.slice(1), current[0]] : current));
  }

  return {
    state, levels, framesSent, connectionStatus, lastEvent, lines, partials, lastTurn, alerts, latencies, notes, error, oneOnOne, useDocuments,
    seeScreen, chosenMeeting, doubt, askingDoubt, start, stop, attention, suggestQuestion, dismissDoubt: () => setDoubt(null),
    dismissCard, nextCard, setOneOnOne, setUseDocuments, setSeeScreen, chooseMeeting, exportMeeting,
  };
}
