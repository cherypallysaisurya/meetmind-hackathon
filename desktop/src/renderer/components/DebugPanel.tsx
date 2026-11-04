import { useState } from "react";
import type { ConnectionStatus, LatencyEvent, ServerEvent } from "../session/ServiceConnection";

// Spec targets, measured from the last word spoken. The answer target arrives with Phase 2.
const TARGETS: Record<string, number> = { last_word_to_alert_s: 1.0, last_word_to_turn_s: 0.7 };

function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor((sorted.length - 1) / 2)];
}

function seconds(value: number | null, target?: number): string {
  if (value === null) return "";
  const text = `${value > 0 ? "+" : ""}${value.toFixed(2)} s`;
  return target !== undefined && value > target ? `${text} (over ${target} s)` : text;
}

type Props = { latencies: LatencyEvent[]; lastStats: ServerEvent | null; connectionStatus: ConnectionStatus; framesSent: number };

// Per question: when the alert fired, when the turn was known and when the classifier answered, all
// relative to the last word spoken. Negative means before the speaker had finished.
export function DebugPanel({ latencies, lastStats, connectionStatus, framesSent }: Props) {
  const [open, setOpen] = useState(false);
  const alertTimes = latencies.map((l) => l.last_word_to_alert_s).filter((v): v is number => v !== null);
  const turnTimes = latencies.map((l) => l.last_word_to_turn_s).filter((v): v is number => v !== null);
  const classifierTimes = latencies.map((l) => l.classifier_ms).filter((v): v is number => v !== null);

  return (
    <div className="debug" data-field="debug">
      <button type="button" className="link" onClick={() => setOpen(!open)}>{open ? "Hide debug" : "Show debug"}</button>
      {open && (
        <div className="debug-body">
          <div>
            Connection {connectionStatus}, {framesSent} frames sent
            {lastStats?.type === "stats" && `, service saw ${lastStats.frames} frames (${lastStats.audio_seconds} s)`}.
          </div>
          <div>
            Medians over {latencies.length} question{latencies.length === 1 ? "" : "s"}:
            alert {seconds(median(alertTimes), TARGETS.last_word_to_alert_s)},
            turn known {seconds(median(turnTimes), TARGETS.last_word_to_turn_s)},
            classifier {median(classifierTimes) ?? ""} ms.
          </div>
          <table>
            <thead>
              <tr><th>Question</th><th>Alert</th><th>Turn known</th><th>Classified</th><th>Classifier</th><th>Result</th></tr>
            </thead>
            <tbody>
              {latencies.map((l) => (
                <tr key={l.alert_id}>
                  <td>{l.question.length > 40 ? l.question.slice(0, 40) + "..." : l.question}</td>
                  <td>{seconds(l.last_word_to_alert_s, TARGETS.last_word_to_alert_s)}</td>
                  <td>{seconds(l.last_word_to_turn_s, TARGETS.last_word_to_turn_s)}</td>
                  <td>{seconds(l.last_word_to_classified_s)}</td>
                  <td>{l.classifier_ms ?? ""} ms</td>
                  <td>{l.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="muted">Times are from the last word spoken. Negative: before the speaker finished. Targets: alert within 1 s, turn known within 0.7 s.</div>
        </div>
      )}
    </div>
  );
}
