// What the user can paste into the meeting chat so everyone knows MeetMind is listening.
// With the Meta model on (the hackathon, decision 0008), the call's text leaves the Mac, and the message says so.
// With See my screen on (decision 0009), it also says that a shared screen may be read.
export function consentMessage(displayName: string, cloudModel: string | null = null, seeScreen = false): string {
  const who = displayName || "I";
  const sent = cloudModel ? ` Text from the call is sent to ${cloudModel} to write answer suggestions.` : "";
  const screen = seeScreen ? " When a question is about something on screen, it reads a picture of the screen; pictures are not kept." : "";
  return (
    `${who === "I" ? "I am" : `${who} is`} using MeetMind, a meeting copilot that transcribes this call ` +
    `for private notes.${sent}${screen} No audio is recorded or stored, only text, and that text is deleted after 30 days.`
  );
}
