import { SILENCE_DB } from "../audio/levels";

export function LevelMeter({ label, db }: { label: string; db: number }) {
  const percent = Math.max(0, Math.min(100, ((db - SILENCE_DB) / -SILENCE_DB) * 100));
  const text = db === -Infinity ? "silence" : `${Math.round(db)} dB`;
  return (
    <div className="meter" data-level={text}>
      <span className="meter-label">{label}</span>
      <span className="meter-bar"><span className="meter-fill" style={{ width: `${percent}%` }} /></span>
      <span className="meter-value">{text}</span>
    </div>
  );
}
