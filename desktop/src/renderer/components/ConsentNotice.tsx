import { useState } from "react";
import { consentMessage } from "../consent";

export function ConsentNotice({ displayName, cloudModel, seeScreen }: { displayName: string; cloudModel: string | null; seeScreen: boolean }) {
  const [copied, setCopied] = useState(false);
  const message = consentMessage(displayName, cloudModel, seeScreen);

  async function copy() {
    await navigator.clipboard.writeText(message);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="consent">
      <div className="consent-title">MeetMind is transcribing</div>
      <p className="consent-text">{message}</p>
      <button type="button" onClick={copy}>{copied ? "Copied" : "Copy message for participants"}</button>
    </div>
  );
}
