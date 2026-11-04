import type { Frame } from "./AudioSource";

export type Levels = { me: number; them: number };   // dB relative to full scale, -Infinity for silence

export const SILENCE_DB = -60;   // the meters show nothing below this

function decibels(frame: Frame, offset: 0 | 1): number {
  let sum = 0;
  for (let i = offset; i < frame.length; i += 2) sum += frame[i] * frame[i];
  const rms = Math.sqrt(sum / (frame.length / 2)) / 32768;
  return rms > 0 ? 20 * Math.log10(rms) : -Infinity;
}

export function levelsOf(frame: Frame): Levels {
  return { me: decibels(frame, 0), them: decibels(frame, 1) };
}
