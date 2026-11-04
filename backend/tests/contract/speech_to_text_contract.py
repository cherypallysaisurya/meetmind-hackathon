"""Contract every SpeechToText adapter must pass.

Subclass this in the adapter's test file, name the class Test..., and implement make_adapter().
The fixture clip has one voice on the left channel saying the left sentence, then a different
voice on the right channel saying the right sentence, with silence on the other channel each time.
"""

import asyncio
import wave
from pathlib import Path

from app.ports import ME, THEM, SpeechToText, Transcript

CLIP = Path(__file__).parent / "fixtures" / "stereo-two-speakers.wav"
FRAME_BYTES = 16000 // 10 * 2 * 2     # 100 ms of stereo 16-bit audio
LEFT_WORD = "left"
RIGHT_WORD = "right"


def clip_bytes_and_seconds():
    with wave.open(str(CLIP)) as w:
        return w.readframes(w.getnframes()), w.getnframes() / w.getframerate()


class SpeechToTextContract:
    def make_adapter(self) -> SpeechToText:
        raise NotImplementedError("the adapter test must build its adapter here")

    async def run_clip(self) -> list[Transcript]:
        """Feed the clip at real-time pace and collect everything the adapter says."""
        adapter = self.make_adapter()
        audio, _ = clip_bytes_and_seconds()
        await adapter.start()

        async def feed_in_real_time():
            for offset in range(0, len(audio), FRAME_BYTES):
                await adapter.feed(audio[offset:offset + FRAME_BYTES])
                await asyncio.sleep(0.1)
            await adapter.stop()

        feeder = asyncio.create_task(feed_in_real_time())
        received = [transcript async for transcript in adapter.transcripts()]
        await feeder
        return received

    async def test_transcribes_both_channels_with_labels_and_times(self):
        received = await self.run_clip()
        _, clip_seconds = clip_bytes_and_seconds()
        finals = [t for t in received if not t.is_partial]
        assert finals, "no final transcripts came back"

        me_text = " ".join(t.text for t in finals if t.channel == ME).lower()
        them_text = " ".join(t.text for t in finals if t.channel == THEM).lower()
        assert LEFT_WORD in me_text, f"left channel should be labeled me, got: {me_text!r}"
        assert RIGHT_WORD in them_text, f"right channel should be labeled them, got: {them_text!r}"
        assert LEFT_WORD not in them_text and RIGHT_WORD not in me_text, "the channels bled into each other"

        for t in received:
            assert t.channel in (ME, THEM)
            assert 0 <= t.start_s <= t.end_s <= clip_seconds + 1.0, f"timestamps outside the clip: {t}"
