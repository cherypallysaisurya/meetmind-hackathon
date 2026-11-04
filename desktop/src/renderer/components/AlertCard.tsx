import type { AlertCardState } from "../useSession";

// The card: the question, then the line to say in large type, the points under it, the sources at the foot.
// It appears the moment Detector A fires and fills in as the answer agent writes.
type Props = { alert: AlertCardState; onDismiss: () => void; onNext: () => void; queued: AlertCardState[] };

function title(alert: AlertCardState): string {
  if (alert.status === "retracted") return "Probably not for you";
  if (alert.answer?.card.tags.claim === "contradicts") return "Your docs say otherwise";
  if (alert.answer?.card.tags.claim === "supports") return "Your docs agree";
  if (alert.answer?.card.tags.asks_to_agree) return "Your call";
  if (alert.answer?.card.tags.low_confidence) return "Key points only";
  if (alert.answer?.card.line) return "Say this";
  return "Question for you";
}

export function AlertCard({ alert, onDismiss, onNext, queued }: Props) {
  const answer = alert.answer;
  const doubtful = alert.status === "retracted";
  return (
    <div className={doubtful ? "card alert-card doubtful" : "card alert-card"} data-field="alert">
      <div className="card-head">
        <span className="card-title">{title(alert)}</span>
        <span className="card-state">
          {alert.status === "candidate" && "checking"}
          {queued.length > 0 && ` +${queued.length} more`}
        </span>
      </div>
      <p className={alert.is_final ? "question" : "question partial"}>{alert.question}</p>

      {answer && (
        <div className={answer.card.tags.low_confidence ? "cue low" : "cue"} data-field="cue" data-done={answer.done ? "yes" : "no"}>
          {answer.card.tags.asks_to_agree && !answer.card.tags.claim
            ? <div className="cue-warning">{answer.done
                ? "You are asked to confirm something about your own work. Your documents do not settle it: answer from what you know. Points for reference:"
                : "You are asked to confirm something about your own work. Checking your documents. Points for reference:"}</div>
            : answer.card.tags.low_confidence && <div className="cue-warning">Low confidence: no line to say, only points</div>}
          {answer.card.line
            ? <p className={answer.card.tags.not_in_docs ? "cue-line not-in-docs" : "cue-line"}>{answer.card.line}</p>
            : !answer.card.tags.low_confidence && <p className="cue-line partial">writing</p>}
          <ul className="cue-points">
            {answer.card.points.map((point, index) => (
              <li key={index} className={answer.card.tags.claim ? "quote" : undefined}>
                {point.text}
                {point.sources.map((n) => <sup key={n} className="source-ref">{n}</sup>)}
              </li>
            ))}
            {answer.card.partial && <li className="partial">{answer.card.partial}</li>}
          </ul>
          <div className="cue-footer">
            {answer.card.confidence && <span className={`chip confidence ${answer.card.confidence}`}>{answer.card.confidence} confidence</span>}
            {answer.sources.map((source) => (
              <span key={source.number} className="chip source" title={`${source.location}: ${source.text}`}>{source.number} {source.document}</span>
            ))}
            {answer.done && answer.card.tags.ungrounded && <span className="chip ungrounded">no document cited</span>}
            {answer.done && answer.label === "prepared" && <span className="chip label">Prepared</span>}
            {answer.card.tags.screen && <span className="chip label">Read your screen</span>}
          </div>
        </div>
      )}

      <div className="card-actions">
        <button type="button" className="link" data-action="dismiss" onClick={onDismiss}>Dismiss</button>
        {queued.length > 0 && <button type="button" className="link" data-action="next" onClick={onNext}>Next</button>}
      </div>
      {queued.length > 0 && (
        <ol className="queue" data-field="queue">
          {queued.map((item) => <li key={item.id}>{item.question}</li>)}
        </ol>
      )}
    </div>
  );
}
