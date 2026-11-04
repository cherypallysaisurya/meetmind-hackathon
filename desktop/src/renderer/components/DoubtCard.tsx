import type { DoubtEvent } from "../session/ServiceConnection";

// A question the user could ask: shown when the room opens up for questions, or when they ask for one.
type Props = { doubt: DoubtEvent; onDismiss: () => void };

export function DoubtCard({ doubt, onDismiss }: Props) {
  return (
    <div className="card doubt-card" data-field="doubt">
      <div className="card-head">
        <span className="card-title">{doubt.question ? "Ask this" : "No question to suggest"}</span>
        <span className="card-state">{doubt.reason === "open floor" ? "the floor is open" : ""}</span>
      </div>
      {doubt.question && <p className="doubt-question">{doubt.question}</p>}
      {doubt.why && <p className="muted">{doubt.why}</p>}
      {doubt.sources.length > 0 && (
        <div className="cue-footer">
          {doubt.sources.map((source) => (
            <span key={source.number} className="chip source" title={`${source.location}: ${source.text}`}>{source.document}</span>
          ))}
        </div>
      )}
      <div className="card-actions">
        <button type="button" className="link" data-action="dismiss-doubt" onClick={onDismiss}>Dismiss</button>
      </div>
    </div>
  );
}
