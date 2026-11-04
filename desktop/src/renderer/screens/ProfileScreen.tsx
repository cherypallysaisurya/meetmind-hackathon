import { useState } from "react";
import { BIO_MAX, PROJECTS_MAX, Profile, splitList } from "../profile";
import { saveProfile } from "../session/api";

type Props = { profile: Profile; onSaved: (profile: Profile) => void };

export function ProfileScreen({ profile, onSaved }: Props) {
  const [draft, setDraft] = useState(profile);
  const [aliasesText, setAliasesText] = useState(profile.aliases.join(", "));
  const [topicsText, setTopicsText] = useState(profile.topics.join(", "));
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function update(field: keyof Profile, value: string) {
    setDraft({ ...draft, [field]: value });
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    const complete = { ...draft, aliases: splitList(aliasesText), topics: splitList(topicsText) };
    try {
      const saved = await saveProfile(complete);
      setSavedAt(new Date().toLocaleTimeString());
      setError(null);
      onSaved(saved);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  }

  return (
    <form className="screen" onSubmit={save}>
      <label>
        Name people call you in meetings
        <input name="displayName" value={draft.displayName} onChange={(e) => update("displayName", e.target.value)} placeholder="Surya" required />
      </label>
      <label>
        Other names or nicknames, comma separated
        <input name="aliases" value={aliasesText} onChange={(e) => setAliasesText(e.target.value)} placeholder="Sur, Suria" />
      </label>
      <label>
        Role
        <input value={draft.role} onChange={(e) => update("role", e.target.value)} placeholder="Junior ML Engineer" />
      </label>
      <label>
        Topics you can speak to, comma separated
        <input value={topicsText} onChange={(e) => setTopicsText(e.target.value)} placeholder="retrieval, evaluation, data pipelines" />
      </label>
      <label>
        About you <span className="counter">{draft.bio.length} / {BIO_MAX}</span>
        <textarea value={draft.bio} maxLength={BIO_MAX} rows={4} onChange={(e) => update("bio", e.target.value)} />
      </label>
      <label>
        Current projects <span className="counter">{draft.currentProjects.length} / {PROJECTS_MAX}</span>
        <textarea value={draft.currentProjects} maxLength={PROJECTS_MAX} rows={6} onChange={(e) => update("currentProjects", e.target.value)} />
      </label>
      <div className="row">
        <button type="submit">Save profile</button>
        {savedAt && <span className="muted" data-field="saved">Saved at {savedAt}</span>}
      </div>
      {error && <p className="error">Could not save: {error}</p>}
    </form>
  );
}
