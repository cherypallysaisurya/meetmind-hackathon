import { useEffect, useRef } from "react";
import type { Partials } from "../useSession";
import type { Channel, TranscriptEvent } from "../session/ServiceConnection";

const LABEL: Record<Channel, string> = { me: "You", them: "Them" };

// The conversation: final lines oldest first, then whatever each side is saying right now in italics.
// It keeps itself scrolled to the newest line.
export function Transcript({ lines, partials }: { lines: TranscriptEvent[]; partials: Partials }) {
  const box = useRef<HTMLDivElement>(null);
  const live = (Object.entries(partials) as [Channel, string | undefined][]).filter(([, text]) => text);

  useEffect(() => {
    const el = box.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines, partials]);

  if (!lines.length && !live.length) return null;
  return (
    <div className="transcript" data-field="transcript" ref={box}>
      {lines.map((line, index) => (
        <div key={index} className={`line ${line.channel}`}>
          <span className="who">{LABEL[line.channel]}</span>
          <span className="said">{line.text}</span>
        </div>
      ))}
      {live.map(([channel, text]) => (
        <div key={channel} className={`line ${channel} partial`}>
          <span className="who">{LABEL[channel]}</span>
          <span className="said">{text}</span>
        </div>
      ))}
    </div>
  );
}
