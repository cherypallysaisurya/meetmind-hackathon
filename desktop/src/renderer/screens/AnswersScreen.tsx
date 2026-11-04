import { AlertCard } from "../components/AlertCard";
import { DoubtCard } from "../components/DoubtCard";
import { Toolbar } from "../components/Toolbar";
import type { useSession } from "../useSession";

type Props = { session: ReturnType<typeof useSession>; attentionArmed: boolean; onAttention: () => void };

// The card and nothing else, so nothing competes with the line to say.
export function AnswersScreen({ session, attentionArmed, onAttention }: Props) {
  const [currentAlert, ...queuedAlerts] = session.alerts;
  const active = session.state === "listening" || session.state === "replaying";
  return (
    <div className="screen answers">
      <Toolbar session={session} attentionArmed={attentionArmed} onAttention={onAttention} />
      <div className="switches">
        <label className="switch">
          <input type="checkbox" id="one-on-one" checked={session.oneOnOne} onChange={(e) => session.setOneOnOne(e.target.checked)} />
          One-on-one: every question is for me
        </label>
        <label className="switch">
          <input type="checkbox" id="use-documents" checked={session.useDocuments} onChange={(e) => session.setUseDocuments(e.target.checked)} />
          Use my documents
        </label>
        <label className="switch" title="A question about something on screen gets a picture of it. macOS asks once for Screen Recording permission.">
          <input type="checkbox" id="see-screen" checked={session.seeScreen} onChange={(e) => session.setSeeScreen(e.target.checked)} />
          See my screen
        </label>
      </div>
      <p className="muted" data-field="chosen-meeting">
        {session.chosenMeeting ? `Prepared meeting: ${session.chosenMeeting.title}` : "No prepared meeting (Prepare tab)"}
      </p>
      {active && (
        <div className="row">
          <button type="button" data-action="suggest" onClick={session.suggestQuestion} disabled={session.askingDoubt}>
            {session.askingDoubt ? "Thinking of a question" : "Suggest a question"}
          </button>
        </div>
      )}
      {session.error && <p className="error">{session.error}</p>}
      {currentAlert
        ? <AlertCard alert={currentAlert} onDismiss={session.dismissCard} onNext={session.nextCard} queued={queuedAlerts} />
        : !session.doubt && <p className="hint">{active ? "Listening. A card appears here when a question is for you." : "Press Start listening when the call begins."}</p>}
      {session.doubt && <DoubtCard doubt={session.doubt} onDismiss={session.dismissDoubt} />}
    </div>
  );
}
