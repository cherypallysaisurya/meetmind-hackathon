import type { AudioSource, Frame } from "./AudioSource";

const RATE = 16000;

// macOS: the mic through getUserMedia, the system audio through Chromium's loopback device
// (Core Audio taps under the hood, see decision 0005). Both land in one 16 kHz AudioContext
// where the frame-builder worklet mixes them into stereo frames.
export class MacAudioSource implements AudioSource {
  private context: AudioContext | null = null;
  private tracks: MediaStreamTrack[] = [];

  async start(onFrame: (frame: Frame) => void, withSystemAudio = true): Promise<void> {
    const noProcessing = { echoCancellation: false, noiseSuppression: false, autoGainControl: false };
    const mic = await navigator.mediaDevices.getUserMedia({ audio: noProcessing, video: false });
    this.tracks = mic.getAudioTracks();
    let system: MediaStream | null = null;
    if (withSystemAudio) {
      // The main process answers this request with our own window as video plus system audio loopback.
      system = await navigator.mediaDevices.getDisplayMedia({ audio: noProcessing, video: true });
      system.getVideoTracks().forEach((track) => track.stop());
      if (!system.getAudioTracks().length) throw new Error("no system audio track");
      this.tracks.push(...system.getAudioTracks());
    }

    this.context = new AudioContext({ sampleRate: RATE });
    await this.context.audioWorklet.addModule(new URL("./frame-builder.js", import.meta.url));
    const builder = new AudioWorkletNode(this.context, "frame-builder", { numberOfInputs: 2, numberOfOutputs: 0 });
    this.context.createMediaStreamSource(mic).connect(builder, 0, 0);
    if (system) this.context.createMediaStreamSource(system).connect(builder, 0, 1);
    builder.port.onmessage = (event) => onFrame(new Int16Array(event.data));
  }

  stop(): void {
    this.tracks.forEach((track) => track.stop());
    this.tracks = [];
    this.context?.close();
    this.context = null;
  }
}
