import { SERVICE_URL } from "../config";
import type { ServiceMode } from "../App";

export function LocalModeBanner({ mode }: { mode: ServiceMode }) {
  if (mode === "unreachable") {
    return (
      <div className="banner error-banner">
        <strong>Service not reachable</strong> at {SERVICE_URL}. Start it with <code>cd backend && .venv/bin/python -m app.main</code>.
      </div>
    );
  }
  return null;   // local mode is stated under "More" on the meeting screen; only a problem gets a banner
}
