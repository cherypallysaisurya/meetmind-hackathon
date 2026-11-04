import { useEffect, useState } from "react";
import { ConsentNotice } from "../components/ConsentNotice";
import { DebugPanel } from "../components/DebugPanel";
import { Toolbar } from "../components/Toolbar";
import { Transcript } from "../components/Transcript";
import type { Profile } from "../profile";
import { getReplays } from "../session/api";
import type { ServerEvent } from "../session/ServiceConnection";
import type { useSession } from "../useSession";
import type { ShortcutAction } from "../../shared/shortcuts";
import type { ServiceMode } from "../App";

type Props = {
  profile: Profile;
  mode: ServiceMode;
  cloudModel: string | null;
  session: ReturnType<typeof useSession>;
  attentionArmed: boolean;
  onAttention: () => void;
  lastShortcut: ShortcutAction | null;
};

function describe(event: ServerEvent | null, status: string): string {
  if (status === "connecting") return "connecting to the service";
  if (status === "closed") return "service not connected";
  if (event?.type === "stats") return `service: ${event.frames} frames, ${event.audio_seconds} s, me ${event.me_db} dB, them ${event.them_db} dB`;
  return "service connected";
}

// The conversation as it is heard, the consent message while listening, the notes, and the details behind "More".
export function ConversationScreen({ profile, mode, cloudModel, session, attentionArmed, onAttention, lastShortcut }: Props) {
  const names = [profile.displayName, ...profile.aliases].filter(Boolean);
  const listening = session.state === "listening";
  const replaying = session.state === "replaying";
  const active = listening || replaying;
  const [replays, setReplays] = useState<string[]>([]);
  const [replayFile, setReplayFile] = useState("");
  const [savedTo, setSavedTo] = useState<string | null>(null);

  async function exportMeeting() {
    const path = await session.exportMeeting();
    if (path) setSavedTo(path);
  }
  const quiet = !session.lines.length && !Object.values(session.partials).some(Boolean);

  useEffect(() => {
    getReplays().then((files) => { setReplays(files); setReplayFile(files[0] ?? ""); }).catch(() => setReplays([]));
  }, []);

  return (
    <div className="screen conversation">
      <Toolbar session={session} attentionArmed={attentionArmed} onAttention={onAttention} />
      {listening && <ConsentNotice displayName={profile.displayName} cloudModel={cloudModel} seeScreen={session.seeScreen} />}

      {quiet
        ? <p className="hint">{active ? "Listening. What is said appears here." : "The conversation appears here once you start listening."}</p>
        : <Transcript lines={session.lines} partials={session.partials} />}

      {session.notes.length > 0 && (
        <details className="notes" data-field="notes">
          <summary className="notes-title">Notes so far ({session.notes.length})</summary>
          <ul>{session.notes.map((note, index) => <li key={index}>{note}</li>)}</ul>
        </details>
      )}

      <div className="row">
        <button type="button" data-action="export" onClick={exportMeeting} disabled={quiet && !session.notes.length}>Export notes</button>
        {savedTo && <span className="muted">Saved to {savedTo}</span>}
      </div>

      <details className="more">
        <summary>More: test replay, shortcuts, details</summary>
        <div className="more-body">
          {!active && session.state === "idle" && replays.length > 0 && (
            <div className="row">
              <select value={replayFile} onChange={(e) => setReplayFile(e.target.value)} data-field="replay-file">
                {replays.map((file) => <option key={file} value={file}>{file.replace(/\.wav$/, "")}</option>)}
              </select>
              <button type="button" data-action="replay" onClick={() => session.start(replayFile)}>Replay test meeting</button>
            </div>
          )}
          <div className="muted" data-field="frames">
            {listening ? `${session.framesSent} frames sent` : replaying ? "replaying a test meeting" : "not listening"}
          </div>
          <div className="muted" data-field="server">{describe(session.lastEvent, session.connectionStatus)}</div>
          <div className="muted" data-field="turn">
            {session.lastTurn
              ? `Last turn: ${session.lastTurn.channel === "me" ? "me" : "them"}, known ${session.lastTurn.delay_s.toFixed(2)} s after the last word`
              : "No turn finished yet"}
          </div>
          <div className="muted">
            {names.length ? `Listening for: ${names.join(", ")}.` : "Add your name on the Profile screen."}
            {" "}Shortcuts: Cmd Shift A attention, Cmd Shift D dismiss card, Cmd Shift N next card.
            {lastShortcut && ` Last: ${lastShortcut}.`}
          </div>
          {mode === "local" && (
            <div className="muted">
              {cloudModel
                ? `Speech is transcribed on this Mac; questions and answers go to ${cloudModel}.`
                : "Local mode: speech and language models run on this Mac, nothing leaves it."}
            </div>
          )}
          <DebugPanel latencies={session.latencies} lastStats={session.lastEvent} connectionStatus={session.connectionStatus} framesSent={session.framesSent} />
        </div>
      </details>
    </div>
  );
}
