// AudioWorklet: input 0 is the mic, input 1 is the system audio. Both are reduced to mono,
// downsampled to 16 kHz if the context runs faster, and interleaved as left = mic,
// right = system into 100 ms frames of 16-bit samples (1600 stereo pairs).

const OUT_RATE = 16000;
const FRAME = OUT_RATE / 10;

class FrameBuilder extends AudioWorkletProcessor {
  constructor() {
    super();
    this.factor = Math.round(sampleRate / OUT_RATE);   // 1 at 16 kHz, 3 at 48 kHz
    this.pending = [[], []];                            // raw mono samples per input, at the context rate
  }

  mono(input) {
    // Average the channels of one input, or silence if nothing is connected.
    const channels = input.length;
    const length = channels ? input[0].length : 128;
    const out = new Float32Array(length);
    if (!channels) return out;
    for (let i = 0; i < length; i++) {
      let sum = 0;
      for (let c = 0; c < channels; c++) sum += input[c][i];
      out[i] = sum / channels;
    }
    return out;
  }

  process(inputs) {
    for (let k = 0; k < 2; k++) {
      const samples = this.mono(inputs[k]);
      for (let i = 0; i < samples.length; i++) this.pending[k].push(samples[i]);
    }
    const needed = FRAME * this.factor;
    while (this.pending[0].length >= needed && this.pending[1].length >= needed) {
      const frame = new Int16Array(FRAME * 2);
      for (let k = 0; k < 2; k++) {
        const raw = this.pending[k].splice(0, needed);
        for (let i = 0; i < FRAME; i++) {
          let sum = 0;
          for (let j = 0; j < this.factor; j++) sum += raw[i * this.factor + j];
          const value = Math.max(-1, Math.min(1, sum / this.factor));
          frame[i * 2 + k] = Math.round(value * 32767);
        }
      }
      this.port.postMessage(frame.buffer, [frame.buffer]);
    }
    return true;
  }
}

registerProcessor("frame-builder", FrameBuilder);
