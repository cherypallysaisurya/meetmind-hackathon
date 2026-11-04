// Where the MeetMind service is. Local by default; Phase 4 points this at the deployed service.
export const SERVICE_URL: string = import.meta.env.VITE_SERVICE_URL ?? "http://127.0.0.1:8080";
export const SERVICE_WS_URL: string = SERVICE_URL.replace(/^http/, "ws") + "/ws";
