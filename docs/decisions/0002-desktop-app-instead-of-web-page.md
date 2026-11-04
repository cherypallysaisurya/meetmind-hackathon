# 0002: Desktop app instead of a web page

Status: accepted (framework choice pending Step 0.6)
Date: 2026-10-22

## Context

The original plan was a React web page in Chrome that captured the microphone plus the audio of a shared browser tab. Spec update 1 adds a requirement: MeetMind must work with meetings in desktop apps (Zoom, Microsoft Teams) as well as in the browser (Google Meet), and it must never join the meeting or add a bot. A web page can only hear a browser tab, so it cannot meet this requirement.

## Options considered

1. **Keep the web page.** Works for Google Meet only. Fails the new requirement.
2. **A bot that joins the meeting.** Would hear everyone, but the spec forbids joining or adding a bot.
3. **A desktop app that captures system audio.** Hears any meeting app on the machine. Needs native audio capture and OS permissions. macOS first, Windows later.

## Decision

Option 3. A desktop shell hosts the existing React UI and adds native system audio capture. Audio capture sits behind an `AudioSource` interface in the desktop app, with a macOS implementation now and a Windows one later.

The audio contract stays the same: mic on the left channel (me), system audio on the right channel (them), stereo 16 kHz PCM over the same WebSocket. The backend is unchanged and runs locally in Phases 0 to 3, then on AWS.

The window is a small always-on-top panel the user can move and resize, with keyboard shortcuts for Attention, dismiss card and next card. In v1 it is a normal visible window.

**Framework:** Electron is the default candidate. Before committing, Step 0.6 checks the current official docs for how each option (Electron, Tauri, a native Swift app) captures system audio on macOS, built-in loopback support versus a small native helper using Apple's ScreenCaptureKit or Core Audio taps, and what macOS version and permissions each needs. That choice gets its own decision record.

## Consequences

- `frontend/` becomes `desktop/`. The inner layout is fixed in Step 0.6.
- A new Step 0.6 proves on the owner's Mac that mic plus system audio can be captured as two channels while Zoom desktop, Teams desktop and Meet in Chrome are running.
- Steps 1.1 and 1.2 build the desktop panel and native capture instead of a browser page.
- The S3 static frontend no longer serves the UI. Whether to keep an S3 + CloudFront download page for the Mac build is an open decision for the owner.
- The definition of done changes from "a deployed HTTPS link where a new user can sign up" to "a Mac build that signs up against the deployed backend". Owner to confirm the wording.
- An unsigned local build is fine for development. Before the event, the owner gets a report on what giving a Mac build to someone else needs (signing, notarization) and how long it takes.
- Hiding the window from screen share is not built unless the owner approves it.
- Bluetooth headphones still do not matter: system audio is captured before it reaches the earbuds.
