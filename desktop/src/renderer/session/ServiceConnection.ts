import type { Frame } from "../audio/AudioSource";

// What the service sends back. Grows with each step; see docs/03-architecture.md section 10.
export type Channel = "me" | "them";

export type TranscriptEvent = {
  type: "transcript";
  channel: Channel;
  text: string;
  is_partial: boolean;   // true while the words may still change
  start_s: number;       // seconds of audio since the session started
  end_s: number;
};

// A speaker finished. delay_s is how long after their last word the service knew it.
export type TurnEvent = { type: "turn"; channel: Channel; text: string; start_s: number; end_s: number; delay_s: number };

// Detector A thinks a question is for the user. Sent when it fires (often on a partial), again with
// is_final true when the final text is in, and once more when Detector B has confirmed or retracted it.
// Same id every time.
export type AlertStatus = "candidate" | "confirmed" | "retracted";

export type AlertEvent = {
  type: "alert";
  id: string;
  question: string;
  score: number;
  reasons: string[];
  start_s: number;
  at_s: number;
  is_final: boolean;
  status: AlertStatus;
  category: string | null;
  confidence: number | null;
};

// One question's timing, once Detector B has answered, and again once the card is done. Seconds are relative to the last word spoken.
export type LatencyEvent = {
  type: "latency";
  alert_id: string;
  question: string;
  status: AlertStatus;
  last_word_to_alert_s: number | null;
  last_word_to_turn_s: number | null;
  last_word_to_classified_s: number | null;
  classifier_ms: number | null;
  last_word_to_first_answer_s: number | null;
  last_word_to_answer_done_s: number | null;
};

// The cue card as the answer model writes it: the line to say, short points with their source numbers,
// the point still being written, and the confidence.
export type CardPoint = { text: string; sources: number[] };
// claim: what the user's documents say about a "you're doing X, right?" question, once the claim checker found it.
// screen: the model saw a picture of the screen with the question.
export type CardTags = { low_confidence: boolean; not_in_docs: boolean; ungrounded: boolean; asks_to_agree: boolean; claim: "supports" | "contradicts" | null; screen: boolean };
export type CardBody = { line: string | null; points: CardPoint[]; partial: string; confidence: string | null; tags: CardTags };
export type CardSource = { number: number; document: string; location: string; text: string };

export type AnswerDeltaEvent = { type: "answer_delta"; alert_id: string; card: CardBody };
export type AnswerDoneEvent = { type: "answer_done"; alert_id: string; card: CardBody; sources: CardSource[]; label: "live" | "prepared" };

export type NotesEvent = { type: "notes_update"; notes: string[] };

// A question the user could ask. question is null when they asked for one and there is nothing new to ask.
export type DoubtEvent = { type: "doubt"; id: string; question: string | null; why: string; sources: CardSource[]; reason: "open floor" | "asked" };

export type ServerEvent =
  | { type: "started"; session_id: string }
  | AlertEvent
  | AnswerDeltaEvent
  | AnswerDoneEvent
  | NotesEvent
  | DoubtEvent
  | LatencyEvent
  | { type: "screen_request"; alert_id: string }   // the question points at the screen: send a picture of it
  | { type: "stats"; frames: number; audio_seconds: number; me_db: number; them_db: number }
  | TranscriptEvent
  | TurnEvent
  | { type: "stopped"; frames: number; audio_seconds: number }
  | { type: "error"; message: string };

export type ConnectionStatus = "closed" | "connecting" | "open";

// One WebSocket to the service: JSON control messages and binary audio frames both go through it.
const STOP_TIMEOUT_MS = 5000;   // how long to wait for the service to flush the last words

export class ServiceConnection {
  private socket: WebSocket | null = null;
  private onStopped: (() => void) | null = null;

  constructor(
    private url: string,
    private onEvent: (event: ServerEvent) => void,
    private onStatus: (status: ConnectionStatus, detail?: string) => void,
  ) {}

  // With a replay file, the service plays that test meeting itself and stops at its end. With a prepared
  // meeting's id, the session is that meeting.
  open(replayFile?: string, prepSessionId?: string): Promise<void> {
    this.onStatus("connecting");
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(this.url);
      socket.binaryType = "arraybuffer";
      socket.onopen = () => {
        this.socket = socket;
        this.onStatus("open");
        socket.send(JSON.stringify({ type: "start", ...(replayFile && { replay_file: replayFile }), ...(prepSessionId && { prep_session_id: prepSessionId }) }));
        resolve();
      };
      socket.onmessage = (message) => {
        const event = JSON.parse(message.data) as ServerEvent;
        if (event.type === "stopped") {
          this.onStopped?.();
          if (!this.onStopped) { socket.close(); this.socket = null; }   // the service ended a replay on its own
        }
        this.onEvent(event);
      };
      socket.onerror = () => reject(new Error(`could not reach the service at ${this.url}`));
      socket.onclose = (event) => {
        this.socket = null;
        this.onStatus("closed", event.reason || undefined);
      };
    });
  }

  sendFrame(frame: Frame): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(frame);   // sent as binary, 6400 bytes
  }

  send(message: object): void {
    this.socket?.send(JSON.stringify(message));
  }

  // Tell the service to stop, wait for its "stopped" (it flushes the last transcripts first), then hang up.
  async close(): Promise<void> {
    const socket = this.socket;
    if (!socket) return;
    this.send({ type: "stop" });
    await new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, STOP_TIMEOUT_MS);
      this.onStopped = () => { clearTimeout(timer); resolve(); };
    });
    this.onStopped = null;
    socket.close();
    this.socket = null;
  }
}
