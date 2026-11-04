import { SILENCE_DB } from "../audio/levels";
import type { useSession } from "../useSession";

const SOUND_DB = SILENCE_DB + 20;   // louder than this counts as someone talking

type Props = { session: ReturnType<typeof useSession>; attentionArmed: boolean; onAttention: () => void };

// Start or stop, the listening state with two sound dots, and the Attention button. The same bar sits on
// the Answers and the Conversation tab, so the controls are always in the same place.
export function Toolbar({ session, attentionArmed, onAttention }: Props) {
  const listening = session.state === "listening";
  const replaying = session.state === "replaying";
  const active = listening || replaying;
  return (
    <div className="toolbar">
      {active || session.state === "stopping" ? (
        <button type="button" data-action="stop" onClick={session.stop} disabled={session.state === "stopping"}>
          {session.state === "stopping" ? "Stopping" : "Stop"}
        </button>
      ) : (
        <button type="button" className="primary" data-action="start" onClick={() => session.start()} disabled={session.state === "starting"}>
          {session.state === "starting" ? "Starting" : "Start listening"}
        </button>
      )}
      <span className="state">
        <span className={active ? "dot live" : "dot"} />
        {listening ? "Listening" : replaying ? "Replaying" : session.state === "starting" ? "Starting" : "Off"}
      </span>
      {active && (
        <span className="activity" title="Sound from you, sound from the others">
          <span className={session.levels.me > SOUND_DB ? "dot on" : "dot"} /> you
          <span className={session.levels.them > SOUND_DB ? "dot on" : "dot"} /> them
        </span>
      )}
      <span className="grow" />
      <button type="button" className={attentionArmed ? "attention armed" : "attention"} onClick={onAttention} title="Cmd Shift A: the last question was for me">
        {attentionArmed ? "Armed" : "Attention"}
      </button>
    </div>
  );
}
