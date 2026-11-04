import type { TranscriptEvent } from "./session/ServiceConnection";
import type { AlertCardState } from "./useSession";

// The meeting as a Markdown file: the notes first, then every card that got an answer, the questions suggested to
// ask, then the conversation.
export function meetingMarkdown(startedAt: Date, notes: string[], cards: AlertCardState[], doubts: string[], lines: TranscriptEvent[]): string {
  const out: string[] = [`# Meeting notes, ${startedAt.toLocaleString()}`, ""];
  out.push("## Notes", "", ...(notes.length ? notes.map((note) => `- ${note}`) : ["(no notes)"]), "");

  const answered = cards.filter((card) => card.answer && (card.answer.card.line || card.answer.card.points.length));
  out.push("## Questions and cards", "");
  if (!answered.length) out.push("(no cards)", "");
  for (const card of answered) {
    const answer = card.answer!;
    out.push(`### ${card.question}`, "");
    if (answer.card.line) out.push(answer.card.line, "");
    for (const point of answer.card.points) {
      const documents = point.sources.map((n) => answer.sources.find((s) => s.number === n)?.document).filter(Boolean);
      out.push(`- ${point.text}${documents.length ? ` (${documents.join(", ")})` : ""}`);
    }
    out.push(`Confidence: ${answer.card.confidence ?? "unknown"}`, "");
  }

  if (doubts.length) out.push("## Questions you could ask", "", ...doubts.map((question) => `- ${question}`), "");

  out.push("## Conversation", "", ...lines.map((line) => `${line.channel === "me" ? "You" : "Them"}: ${line.text}`), "");
  return out.join("\n");
}
