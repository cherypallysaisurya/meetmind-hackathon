import numpy as np

from app.audio.frames import FRAME_BYTES, SAMPLES_PER_CHANNEL, SILENCE_DB, level_db, split_channels, sum_of_squares


def make_frame(left: int, right: int) -> bytes:
    """A frame where every left sample is `left` and every right sample is `right`."""
    samples = np.empty(SAMPLES_PER_CHANNEL * 2, dtype=np.int16)
    samples[0::2] = left
    samples[1::2] = right
    return samples.tobytes()


def test_a_frame_is_100ms_of_stereo_16bit_audio():
    assert FRAME_BYTES == 6400
    assert len(make_frame(0, 0)) == FRAME_BYTES


def test_split_channels_keeps_left_as_me_and_right_as_them():
    me, them = split_channels(make_frame(1000, -2000))
    assert len(me) == len(them) == SAMPLES_PER_CHANNEL
    assert set(me.tolist()) == {1000}
    assert set(them.tolist()) == {-2000}


def test_level_db_floors_silence_and_tops_at_full_scale():
    assert level_db(0.0, SAMPLES_PER_CHANNEL) == SILENCE_DB
    full_scale = np.full(SAMPLES_PER_CHANNEL, 32767, dtype=np.int16)
    assert -0.01 < level_db(sum_of_squares(full_scale), SAMPLES_PER_CHANNEL) <= 0.0
    half_scale = np.full(SAMPLES_PER_CHANNEL, 16384, dtype=np.int16)
    assert round(level_db(sum_of_squares(half_scale), SAMPLES_PER_CHANNEL)) == -6
