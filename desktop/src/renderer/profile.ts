// The user's profile: who they are, what they are called in meetings, what they know about.
// Saved through the service (session/api.ts), which keeps it in the store.

export type Profile = {
  displayName: string;
  aliases: string[];
  role: string;
  topics: string[];
  bio: string;
  currentProjects: string;
};

export const BIO_MAX = 2000;
export const PROJECTS_MAX = 4000;

export const emptyProfile: Profile = {
  displayName: "",
  aliases: [],
  role: "",
  topics: [],
  bio: "",
  currentProjects: "",
};

// "Surya, Sur, S" -> ["Surya", "Sur", "S"]
export function splitList(text: string): string[] {
  return text.split(",").map((item) => item.trim()).filter(Boolean);
}
