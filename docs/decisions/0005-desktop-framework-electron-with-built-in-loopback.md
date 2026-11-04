# 0005: Desktop framework: Electron with Chromium's built-in system audio loopback

Status: accepted
Date: 2026-10-22

## Context

Decision 0002 made MeetMind a desktop app so it can hear Zoom and Teams, not only a browser tab. The open question was how to capture system audio on macOS: a framework with built-in loopback, or a small native helper using Apple's ScreenCaptureKit or Core Audio taps. Step 0.6 settled it with a spike on the owner's Mac (macOS 26.6.2, Electron 45.0.0, Chromium 156).

## Options considered

1. **Electron with Chromium's built-in loopback.** Since Electron 39, Chromium on macOS 14.2 and later captures system audio through Apple's Core Audio Tap API. The page calls `getDisplayMedia({ audio: true, video: true })` and the main process answers the request with `audio: "loopback"`. No native code.
2. **Electron plus a Swift helper** that creates a Core Audio tap or a ScreenCaptureKit stream and writes PCM to a pipe. Full control, but a second binary to build, sign and keep in sync.
3. **Tauri with a Rust or Swift plugin.** Smaller binary, but the same native helper work as option 2 and a less common WebView audio stack.
4. **A native Swift app** hosting the React UI in a WKWebView. The most work, and it throws away the existing web audio code.

## Decision

Option 1. Measured in the spike (`desktop/spike/`): mic and system audio in one 16 kHz AudioContext, mixed by an AudioWorklet into 100 ms frames of interleaved stereo 16-bit PCM, left = mic, right = system. While `say` spoke through the speakers, the right channel sat at -18 to -21 dB and was silent otherwise; the mic heard the same sentence acoustically at -30 dB. The chosen STT model transcribed the right channel as the exact sentence. 99 frames in 10 seconds.

Two details made it work without Screen Recording permission:
- The display media handler returns the app's own window frame as the video source instead of a screen from `desktopCapturer`. Enumerating screens needs Screen Recording permission and failed here. The video track is stopped immediately; only the loopback audio is used.
- Chromium applies echo cancellation, noise suppression and gain control to the loopback track by default and downmixes it to mono. Passing those three constraints as `false` gives the raw stereo system audio.

## Consequences

- **Permission model.** macOS gates the tap behind "System Audio Recording" and attributes it to the responsible process. Launched from a shell, that process is the terminal or editor, and the loopback track then arrives live but silent, with no error. In development the app is launched with `open -n -a node_modules/electron/dist/Electron.app --args "$(pwd)"` (the `npm run spike` script) so Electron itself asks. The packaged app in Phase 5 needs `NSAudioCaptureUsageDescription` and `NSMicrophoneUsageDescription` in its Info.plist; the development binary already has them.
- **Minimum macOS 14.2** for system audio. Older Macs would need a virtual audio device, which v1 does not support.
- **Windows later.** Chromium's loopback was Windows first, so the same code path is the plan for the Windows AudioSource, to be verified then.
- **Crosstalk without headphones.** When the meeting plays through the speakers, the mic also hears it. With headphones this does not happen. Step 1.2 keeps echo cancellation available on the mic track as a setting for speaker use.
- **One frame of warm up.** The first 100 ms frame is lost while the worklet fills; 99 of 100 frames arrive.
- Step 1.1 sets up the real app around this: TypeScript, React, a build tool, the always-on-top panel and shortcuts. Step 1.2 turns the spike into the `AudioSource` interface with this macOS implementation.
- To do by the owner, since it needs a human at the Mac: run the spike while Zoom desktop, Teams desktop and Google Meet in Chrome each play audio, and approve the two permission prompts (microphone, system audio) for Electron if they appear.
