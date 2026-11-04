import { app, BrowserWindow, desktopCapturer, dialog, globalShortcut, ipcMain, screen, session, systemPreferences } from "electron";
import { spawn } from "node:child_process";
import { appendFileSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { SHORTCUTS } from "../shared/shortcuts";

// --smoke: load the app, print what is on screen, start listening while the Mac speaks a sentence,
// print the meters, quit. Lets us verify the app without a person. Output also goes to out/smoke.log,
// because stdout is invisible when the app is launched with `open`.
const smoke = process.argv.includes("--smoke");
const SMOKE_LOG = join(__dirname, "../smoke.log");
const SMOKE_SENTENCE = "Surya, what batch size did you end up using for the last training run?";
const SMOKE_SCREEN_QUESTION = "Surya, what do you make of what is on the screen?";

function log(line: string): void {
  console.log(line);
  if (smoke) {
    mkdirSync(join(__dirname, ".."), { recursive: true });
    appendFileSync(SMOKE_LOG, line + "\n");
  }
}

// The page hands over a file name and its text; the user picks where it goes.
ipcMain.handle("save-file", async (_event, name: string, text: string) => {
  const { canceled, filePath } = await dialog.showSaveDialog({ defaultPath: join(app.getPath("documents"), name) });
  if (canceled || !filePath) return null;
  writeFileSync(filePath, text);
  return filePath;
});

// A picture of the screen for a question that points at it ("what do you make of this chart?"), decision 0009.
// The display under the mouse pointer, which is where the user looks at the meeting. macOS asks once for Screen
// Recording permission; without it there is no picture and the card is written without one.
const SCREEN_WIDTH = 1440;   // wide enough to read a slide's labels and numbers, small enough to send quickly

ipcMain.handle("capture-screen", async () => {
  const display = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
  const scale = Math.min(1, SCREEN_WIDTH / display.size.width);
  const sources = await desktopCapturer.getSources({
    types: ["screen"],
    thumbnailSize: { width: Math.round(display.size.width * scale), height: Math.round(display.size.height * scale) },
  });
  if (systemPreferences.getMediaAccessStatus("screen") !== "granted") return null;
  const source = sources.find((s) => s.display_id === String(display.id)) ?? sources[0];
  if (!source || source.thumbnail.isEmpty()) return null;
  return source.thumbnail.toJPEG(70).toString("base64");
});

function allowSystemAudioLoopback(): void {
  // The page asks for display media only to get system audio. We answer with the page's own frame as
  // the video (it stops that track at once) and the system audio loopback. No Screen Recording permission
  // is needed this way, only System Audio Recording. See decision 0005.
  session.defaultSession.setDisplayMediaRequestHandler((request, callback) => {
    callback({ video: request.frame ?? undefined, audio: "loopback" });
  });
}

function createWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 380,
    height: 600,
    minWidth: 320,
    minHeight: 420,
    title: "MeetMind",
    alwaysOnTop: true,
    titleBarStyle: "hiddenInset",
    webPreferences: { preload: join(__dirname, "../preload/index.js") },
  });
  // Stay visible over a full screen meeting app and follow the user across Spaces.
  window.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });

  if (process.env.ELECTRON_RENDERER_URL) {
    window.loadURL(process.env.ELECTRON_RENDERER_URL);   // electron-vite dev server
  } else {
    window.loadFile(join(__dirname, "../renderer/index.html"));
  }
  return window;
}

function registerShortcuts(window: BrowserWindow): void {
  for (const [keys, action] of Object.entries(SHORTCUTS)) {
    const registered = globalShortcut.register(keys, () => window.webContents.send("shortcut", action));
    log(`shortcut ${keys} -> ${action}: ${registered ? "registered" : "FAILED, taken by another app"}`);
  }
}

async function runSmokeCheck(window: BrowserWindow): Promise<void> {
  const pause = (ms = 300) => new Promise((resolve) => setTimeout(resolve, ms));
  let smokeDocumentAdded = false;
  const run = (code: string) =>
    window.webContents.executeJavaScript(code).catch((error: Error) => {
      throw new Error(`${error.message} while running: ${code.trim().slice(0, 90)}`);
    });
  const click = (selector: string) => run(`document.querySelector("${selector}").click()`);
  const text = (selector = "body") => run(`document.querySelector("${selector}").innerText`);

  await pause();
  log(`title: ${window.getTitle()}`);
  const tabCount: number = await run("document.querySelectorAll('.tabs button').length");
  for (let i = 0; i < tabCount; i++) {
    await run(`document.querySelectorAll('.tabs button')[${i}].click()`);
    await pause();
    log(`--- tab ${i + 1} ---`);
    log(await text());
  }

  // Documents: add a small markdown file through the file input, then read the list.
  await click(".tabs button:nth-child(4)");   // Documents
  await pause(500);
  await run(`(() => {
    const input = document.querySelector("[data-field=file-input]");
    const file = new File([${JSON.stringify("# Training\n\nThe last training run used batch size 32 with gradient accumulation of 4 on one GPU.\n\n# Results\n\nThe rebuild takes twelve minutes instead of forty.\n")}], "smoke-notes.md", { type: "text/markdown" });
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  })()`);
  await pause(4000);
  log(`--- documents: ${(await text("[data-field=documents]")).replace(/\n/g, " | ")}`);
  smokeDocumentAdded = true;

  // A profile is needed before a session can start. Fill and save one if none is loaded.
  await click(".tabs button:nth-child(5)");   // Profile
  await pause();
  const hasName: boolean = await run(`document.querySelector("input[name=displayName]").value.length > 0`);
  if (!hasName) {
    // Wrapped in a function: executeJavaScript runs in the page's global scope, where a second
    // top-level const with the same name would be a redeclaration error.
    const type = (name: string, value: string) => run(`(() => {
      const field = document.querySelector("input[name=${name}]");
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(field, ${JSON.stringify(value)});
      field.dispatchEvent(new Event("input", { bubbles: true }));
    })()`);
    await type("displayName", "Surya");
    await type("aliases", "Sur, Suria");
    await click("button[type=submit]");
    await pause(800);
  }
  log(`--- profile: ${hasName ? "already saved" : "saved now"}`);

  // Audio: start listening on the Answers tab, speak through the speakers, watch the sound dots.
  // The status fields live on the Conversation tab behind "More".
  const conversationTab = async () => {
    await click(".tabs button:nth-child(2)");
    await pause();
    await run(`(() => { const more = document.querySelector(".more"); if (more) more.open = true; })()`);
  };
  await click(".tabs button");
  await pause();
  await click("[data-action=start]");
  await pause(1500);
  await conversationTab();
  log(`--- listening: ${await text("[data-field=frames]")}`);
  spawn("say", ["-v", "Daniel", SMOKE_SENTENCE]);
  for (let second = 1; second <= 8; second++) {
    await pause(1000);
    const sound: string = await run(`[...document.querySelectorAll(".activity .dot")].map((dot) => dot.className.includes("on") ? "sound" : "quiet").join(" / ")`);
    log(`t=${second}s  you / them: ${sound}  |  ${await text("[data-field=server]")}`.replace(/\n/g, "  "));
  }
  log(`--- after 8 s: ${await text("[data-field=frames]")}`);
  log(`--- transcript:\n${await text("[data-field=transcript]")}`);
  log(`--- ${await text("[data-field=turn]")}`);
  // Detector B needs a couple of seconds, the cue card a few more. Wait up to 20 s for the card to finish.
  await click(".tabs button");   // the card is on the Answers tab
  await pause();
  for (let waited = 0; waited < 20; waited++) {
    await pause(1000);
    const done: boolean = await run(`document.querySelector("[data-field=cue][data-done=yes]") !== null`);
    if (done) break;
  }
  const alertShown: boolean = await run(`document.querySelector("[data-field=alert]") !== null`);
  log(`--- alert card: ${alertShown ? (await text("[data-field=alert]")).replace(/\n/g, " | ") : "none"}`);
  // Suggest a question (decision 0009): one sentence was said, so the service should say there is nothing to ask yet.
  await click("[data-action=suggest]");
  for (let waited = 0; waited < 20 && !(await run(`document.querySelector("[data-field=doubt]") !== null`)); waited++) await pause(1000);
  const doubtShown: boolean = await run(`document.querySelector("[data-field=doubt]") !== null`);
  log(`--- suggest a question: ${doubtShown ? (await text("[data-field=doubt]")).replace(/\n/g, " | ") : "nothing came back"}`);
  // See my screen: one picture through the same bridge the card uses; null means Screen Recording is not allowed yet.
  const picture: number | null = await run(`window.meetmind.captureScreen().then((jpeg) => jpeg ? jpeg.length : null)`);
  log(`--- screen picture: ${picture === null ? "none (Screen Recording not allowed for this app yet)" : `${Math.round((picture * 3) / 4 / 1024)} KB JPEG`}`);
  await conversationTab();
  await click("[data-field=debug] button");
  await pause();
  log(`--- debug panel:\n${await text("[data-field=debug]")}`);
  await click("[data-action=stop]");
  await pause(6000);   // the notes agent catches up once at stop
  log(`--- stopped: ${await text("[data-field=frames]")}  |  ${await text("[data-field=server]")}`);
  const notesShown: boolean = await run(`document.querySelector("[data-field=notes]") !== null`);
  log(`--- notes: ${notesShown ? (await text("[data-field=notes]")).replace(/\n/g, " | ") : "none"}`);

  // See my screen, end to end: a question about the screen is answered with a picture of it.
  await click(".tabs button");
  await pause();
  const screenWasOn: boolean = await run(`document.querySelector("#see-screen").checked`);
  if (!screenWasOn) await click("#see-screen");
  await click("[data-action=start]");
  await pause(2500);
  spawn("say", ["-v", "Daniel", SMOKE_SCREEN_QUESTION]);
  for (let waited = 0; waited < 40; waited++) {
    await pause(1000);
    if (await run(`document.querySelector("[data-field=cue][data-done=yes]") !== null`)) break;
  }
  const screenCard: boolean = await run(`document.querySelector("[data-field=alert]") !== null`);
  log(`--- screen question card: ${screenCard ? (await text("[data-field=alert]")).replace(/\n/g, " | ") : "none"}`);
  await click("[data-action=stop]");
  await pause(3000);
  if (!screenWasOn) await click("#see-screen");

  // Replay: the service plays a test meeting into the session, no microphone involved.
  const hasReplays: boolean = await run(`document.querySelector("[data-action=replay]") !== null`);
  if (hasReplays) {
    log(`--- replaying: ${await run(`document.querySelector("[data-field=replay-file]").value`)}`);
    await click("[data-action=replay]");
    await pause(9000);
    log(`--- replay state: ${await text("[data-field=frames]")}  |  ${await text("[data-field=server]")}`);
    const linesShown: number = await run(`document.querySelectorAll("[data-field=transcript] .line").length`);
    log(`--- replay transcript lines after 9 s: ${linesShown}`);
    await click("[data-action=stop]");
    await pause(2500);
    log(`--- replay stopped: ${await text("[data-field=frames]")}`);
  } else {
    log("--- no replay files listed");
  }

  // Rehearsal (decision 0009): open the first prepared meeting's cards, rehearse, record a moment from the mic.
  await click(".tabs button:nth-child(3)");   // Prepare
  await pause(800);
  if (await run(`document.querySelector("[data-action=cards]") !== null`)) {
    await click("[data-action=cards]");
    await pause(1500);
    if (await run(`document.querySelector("[data-action=rehearse]") !== null`)) {
      await click("[data-action=rehearse]");
      await pause(800);
      log(`--- rehearse question: ${await text("[data-field=rehearse-question]")}`);
      await click("[data-action=answer]");
      await pause(3000);
      await click("[data-action=done]");
      for (let waited = 0; waited < 30 && (await run(`!document.querySelector("[data-field=check]") && !document.querySelector(".rehearse .error")`)); waited++) await pause(1000);
      log(`--- rehearse result: ${(await text(".rehearse")).replace(/\n/g, " | ").slice(0, 400)}`);
    } else {
      log("--- rehearse: the first prepared meeting has no cards");
    }
  } else {
    log("--- rehearse: no prepared meeting");
  }

  // Leave the documents as we found them: remove every copy of the smoke's own file.
  if (smokeDocumentAdded) {
    await click(".tabs button:nth-child(4)");   // Documents
    await pause(800);
    const removed: number = await run(`(() => {
      const rows = [...document.querySelectorAll("[data-field=documents] .document")].filter((row) => row.textContent.includes("smoke-notes.md"));
      rows.forEach((row) => row.querySelector("button").click());
      return rows.length;
    })()`);
    await pause(1500);
    log(`--- cleanup: removed ${removed} smoke document(s), list now: ${(await text("[data-field=documents]")).replace(/\n/g, " | ")}`);
  }
  app.quit();
}

app.whenReady().then(() => {
  allowSystemAudioLoopback();
  const window = createWindow();
  registerShortcuts(window);
  if (smoke) {
    window.webContents.on("console-message", (event) => {
      if (event.level === "error") log(`renderer error: ${event.message}`);
    });
    window.webContents.on("did-finish-load", () =>
      runSmokeCheck(window).catch((error) => { log(`SMOKE FAILED: ${error.message}`); app.quit(); }),
    );
    setTimeout(() => { log("smoke safety timeout, quitting"); app.quit(); }, 180000);
  }
});

app.on("will-quit", () => globalShortcut.unregisterAll());
app.on("window-all-closed", () => app.quit());
