import { useEffect, useState } from "react";
import { LocalModeBanner } from "./components/LocalModeBanner";
import { emptyProfile, Profile } from "./profile";
import { DocumentsScreen } from "./screens/DocumentsScreen";
import { PrepareScreen } from "./screens/PrepareScreen";
import { AnswersScreen } from "./screens/AnswersScreen";
import { ConversationScreen } from "./screens/ConversationScreen";
import { ProfileScreen } from "./screens/ProfileScreen";
import { getHealth, getProfile } from "./session/api";
import { useSession } from "./useSession";
import type { ShortcutAction } from "../shared/shortcuts";

type Screen = "answers" | "conversation" | "prepare" | "documents" | "profile";
export type ServiceMode = "local" | "cognito" | "unknown" | "unreachable";

const ATTENTION_WINDOW_MS = 15000;   // how long an Attention press stays armed

export function App() {
  const [mode, setMode] = useState<ServiceMode>("unknown");
  const [cloudModel, setCloudModel] = useState<string | null>(null);   // the language model, when it runs outside this Mac
  const [profile, setProfile] = useState<Profile>(emptyProfile);
  const [screen, setScreen] = useState<Screen>("profile");
  const [attentionArmed, setAttentionArmed] = useState(false);
  const [lastShortcut, setLastShortcut] = useState<ShortcutAction | null>(null);
  const session = useSession();

  function pressAttention() {
    session.attention();
    setAttentionArmed(true);
    setTimeout(() => setAttentionArmed(false), ATTENTION_WINDOW_MS);
  }

  // On launch: ask the service which mode it runs in and load the saved profile.
  useEffect(() => {
    (async () => {
      try {
        const health = await getHealth();
        setMode(health.mode);
        setCloudModel(health.llm === "meta" ? `Meta's ${health.answerModel} model` : null);
        const saved = await getProfile();
        if (saved) {
          setProfile(saved);
          setScreen("answers");
        }
      } catch {
        setMode("unreachable");
      }
    })();
  }, []);

  useEffect(() => {
    return window.meetmind.onShortcut((action) => {
      setLastShortcut(action);
      if (action === "attention") pressAttention();
      if (action === "dismiss-card") session.dismissCard();
      if (action === "next-card") session.nextCard();
    });
  }, [session.attention, session.dismissCard, session.nextCard]);

  return (
    <div className="app">
      <div className="titlebar">MeetMind</div>
      <LocalModeBanner mode={mode} />
      <nav className="tabs">
        <button type="button" className={screen === "answers" ? "active" : ""} onClick={() => setScreen("answers")}>Answers</button>
        <button type="button" className={screen === "conversation" ? "active" : ""} onClick={() => setScreen("conversation")}>Conversation</button>
        <button type="button" className={screen === "prepare" ? "active" : ""} onClick={() => setScreen("prepare")}>Prepare</button>
        <button type="button" className={screen === "documents" ? "active" : ""} onClick={() => setScreen("documents")}>Documents</button>
        <button type="button" className={screen === "profile" ? "active" : ""} onClick={() => setScreen("profile")}>Profile</button>
      </nav>
      {screen === "answers" && <AnswersScreen session={session} attentionArmed={attentionArmed} onAttention={pressAttention} />}
      {screen === "conversation" && (
        <ConversationScreen profile={profile} mode={mode} cloudModel={cloudModel} session={session} attentionArmed={attentionArmed} onAttention={pressAttention} lastShortcut={lastShortcut} />
      )}
      {screen === "prepare" && <PrepareScreen chosenId={session.chosenMeeting?.sessionId ?? null} onChoose={session.chooseMeeting} />}
      {screen === "documents" && <DocumentsScreen />}
      {screen === "profile" && (
        <ProfileScreen profile={profile} onSaved={(saved) => { setProfile(saved); setScreen("answers"); }} />
      )}
    </div>
  );
}
