import { contextBridge, ipcRenderer } from "electron";
import type { ShortcutAction } from "../shared/shortcuts";

// Everything the page may call lives here. The page has no other access to Electron or Node.
const meetmind = {
  onShortcut(handler: (action: ShortcutAction) => void): () => void {
    const listener = (_event: unknown, action: ShortcutAction) => handler(action);
    ipcRenderer.on("shortcut", listener);
    return () => ipcRenderer.removeListener("shortcut", listener);
  },
  // Save text as a file where the user chooses. Resolves to the path, or null when they cancel.
  saveFile(name: string, text: string): Promise<string | null> {
    return ipcRenderer.invoke("save-file", name, text);
  },
  // A picture of the screen as base64 JPEG, or null without Screen Recording permission.
  captureScreen(): Promise<string | null> {
    return ipcRenderer.invoke("capture-screen");
  },
};

export type MeetMindBridge = typeof meetmind;

contextBridge.exposeInMainWorld("meetmind", meetmind);
