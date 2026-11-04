import type { MeetMindBridge } from "../preload/index";

declare global {
  interface Window {
    meetmind: MeetMindBridge;
  }
}

export {};
