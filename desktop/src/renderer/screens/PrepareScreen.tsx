import { useEffect, useState } from "react";
import { splitList } from "../profile";
import { createPrepared, deletePrepared, getDocuments, getPrepared, updatePrepared, type PreparedMeeting } from "../session/api";
import { PreparedCardsScreen } from "./PreparedCardsScreen";

type Props = { chosenId: string | null; onChoose: (meeting: PreparedMeeting | null) => void };

const EMPTY = { title: "", agenda: "", participants: "" };

// Meetings prepared ahead of time: the agenda and who attends. The one chosen here is used when you press
// Start listening; Phase 2P builds its predicted questions and prepared cards from it and your documents.
export function PrepareScreen({ chosenId, onChoose }: Props) {
  const [meetings, setMeetings] = useState<PreparedMeeting[]>([]);
  const [documentCount, setDocumentCount] = useState(0);
  const [editing, setEditing] = useState<string | null>(null);   // a meeting's id, "new", or null for the list
  const [draft, setDraft] = useState(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [reviewing, setReviewing] = useState<PreparedMeeting | null>(null);

  async function refresh() {
    try {
      setMeetings(await getPrepared());
      setDocumentCount((await getDocuments()).length);
      setError(null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  }

  useEffect(() => { refresh(); }, []);

  function edit(meeting: PreparedMeeting | null) {
    setEditing(meeting ? meeting.sessionId : "new");
    setDraft(meeting ? { title: meeting.title, agenda: meeting.agenda, participants: meeting.participants.join(", ") } : EMPTY);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    const body = { title: draft.title, agenda: draft.agenda, participants: splitList(draft.participants) };
    try {
      const saved = editing === "new" ? await createPrepared(body) : await updatePrepared(editing!, body);
      if (editing === "new" || saved.sessionId === chosenId) onChoose(saved);
      setEditing(null);
      await refresh();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  }

  async function remove(meeting: PreparedMeeting) {
    await deletePrepared(meeting.sessionId);
    if (meeting.sessionId === chosenId) onChoose(null);
    await refresh();
  }

  if (reviewing) return <PreparedCardsScreen meeting={reviewing} onBack={() => setReviewing(null)} />;

  if (editing) {
    return (
      <form className="screen" onSubmit={save}>
        <label>
          Meeting
          <input id="prep-title" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} placeholder="Dana 1:1, Thursday" required />
        </label>
        <label>
          Agenda, pasted as it is
          <textarea id="prep-agenda" value={draft.agenda} rows={8} onChange={(e) => setDraft({ ...draft, agenda: e.target.value })} required />
        </label>
        <label>
          Who attends, comma separated
          <input id="prep-participants" value={draft.participants} onChange={(e) => setDraft({ ...draft, participants: e.target.value })} placeholder="Dana, Lee" />
        </label>
        <p className="muted">Answers draw on your {documentCount} document{documentCount === 1 ? "" : "s"} from the Documents tab.</p>
        <div className="row">
          <button type="submit">Save meeting</button>
          <button type="button" className="link" onClick={() => setEditing(null)}>Cancel</button>
        </div>
        {error && <p className="error">Could not save: {error}</p>}
      </form>
    );
  }

  return (
    <div className="screen">
      <p className="muted">Prepare a meeting before it starts: paste the agenda and who attends. The one you pick is used when you press Start listening.</p>
      <div className="row">
        <button type="button" className="primary" data-action="new-meeting" onClick={() => edit(null)}>Prepare a meeting</button>
      </div>
      {error && <p className="error">{error}</p>}
      <ul className="documents" data-field="prepared">
        {meetings.length === 0 && <li className="muted">No prepared meetings yet.</li>}
        {meetings.map((meeting) => (
          <li key={meeting.sessionId} className="document">
            <label className="switch document-name">
              <input type="radio" name="chosen-meeting" checked={meeting.sessionId === chosenId} onChange={() => onChoose(meeting)} />
              {meeting.title}{meeting.held ? " (held)" : ""}
            </label>
            <button type="button" className="link" data-action="cards" onClick={() => setReviewing(meeting)}>Cards</button>
            <button type="button" className="link" onClick={() => edit(meeting)}>Edit</button>
            <button type="button" className="link" onClick={() => remove(meeting)}>Remove</button>
          </li>
        ))}
      </ul>
      {chosenId && <button type="button" className="link" onClick={() => onChoose(null)}>Start the next meeting without preparation</button>}
    </div>
  );
}
