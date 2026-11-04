// The three things the user can do from the keyboard while another app has the focus.
// Shared by the main process (registers them) and the renderer (reacts to them).

export const SHORTCUTS = {
  "CommandOrControl+Shift+A": "attention",
  "CommandOrControl+Shift+D": "dismiss-card",
  "CommandOrControl+Shift+N": "next-card",
} as const;

export type ShortcutAction = (typeof SHORTCUTS)[keyof typeof SHORTCUTS];
