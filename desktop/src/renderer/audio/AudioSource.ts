// Where the audio comes from. One implementation per platform, same shape for the rest of the app.
//
// A frame is 100 ms of interleaved stereo 16-bit PCM at 16 kHz: 1600 pairs, left = me (mic),
// right = them (system audio). These are the exact bytes the service receives over the WebSocket.

import { MacAudioSource } from "./MacAudioSource";

export type Frame = Int16Array<ArrayBuffer>;

export interface AudioSource {
  // withSystemAudio false: the microphone alone (rehearsal); the right channel stays silent.
  start(onFrame: (frame: Frame) => void, withSystemAudio?: boolean): Promise<void>;
  stop(): void;
}

export function createAudioSource(): AudioSource {
  // Windows gets its own class here later. Only macOS is built for now.
  return new MacAudioSource();
}
