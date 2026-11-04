from app.ports import ME, THEM, Transcript
from app.turns.end_of_turn import EndOfTurnDetector


def partial(channel, text, start, end):
    return Transcript(channel, text, True, start, end)


def final(channel, text, start, end):
    return Transcript(channel, text, False, start, end)


def test_partials_mark_the_speaker_and_finals_make_turns_with_their_delay():
    detector = EndOfTurnDetector()
    assert detector.on_transcript(partial(THEM, "what batch", 10.0, 11.0), audio_now_s=11.1) is None
    assert detector.is_speaking(THEM)
    assert not detector.is_speaking(ME)

    turn = detector.on_transcript(final(THEM, "what batch size did you use", 10.0, 12.4), audio_now_s=13.2)
    assert turn is not None
    assert turn.text == "what batch size did you use"
    assert turn.delay_s == 0.8
    assert not detector.is_speaking(THEM)
    assert detector.last_turn(THEM) == turn
    assert detector.last_turn(ME) is None


def test_recent_returns_turns_inside_the_window_oldest_first():
    detector = EndOfTurnDetector()
    detector.on_transcript(final(THEM, "old", 0.0, 2.0), audio_now_s=2.5)
    detector.on_transcript(final(ME, "mine", 50.0, 52.0), audio_now_s=52.5)
    detector.on_transcript(final(THEM, "new", 60.0, 61.0), audio_now_s=61.5)
    assert [t.text for t in detector.recent(seconds=15, now_s=61.5)] == ["mine", "new"]
    assert [t.text for t in detector.recent(seconds=100, now_s=61.5)] == ["old", "mine", "new"]


def test_old_turns_are_forgotten():
    detector = EndOfTurnDetector(keep_seconds=30)
    detector.on_transcript(final(THEM, "old", 0.0, 2.0), audio_now_s=2.5)
    detector.on_transcript(final(THEM, "new", 40.0, 41.0), audio_now_s=41.5)
    assert [t.text for t in detector.turns] == ["new"]


def test_a_me_turn_that_repeats_them_is_an_echo_and_does_not_count_as_speaking():
    detector = EndOfTurnDetector()
    detector.on_transcript(final(THEM, "Surya, what batch size did you use?", 10.0, 13.0), audio_now_s=13.8)
    echo = detector.on_transcript(final(ME, "Suria, what batch size did you use?", 10.2, 13.2), audio_now_s=14.0)
    assert echo.echo
    assert detector.last_turn(ME) is None

    real = detector.on_transcript(final(ME, "I used thirty two.", 15.0, 16.5), audio_now_s=17.0)
    assert not real.echo
    assert detector.last_turn(ME) == real


def test_an_echo_transcribed_before_the_them_final_is_flagged_when_the_final_arrives():
    detector = EndOfTurnDetector()
    early_echo = detector.on_transcript(final(ME, "what batch size did you end up using for the last run?", 10.3, 13.1), audio_now_s=13.9)
    assert not early_echo.echo            # nothing to compare with yet
    assert detector.last_turn(ME) == early_echo
    detector.on_transcript(final(THEM, "Surya, what batch size did you end up using for the last run?", 10.0, 13.0), audio_now_s=14.0)
    assert early_echo.echo
    assert detector.last_turn(ME) is None


def test_last_turn_can_ignore_turns_that_overlap_the_current_utterance():
    detector = EndOfTurnDetector()
    before = detector.on_transcript(final(ME, "I used thirty two.", 5.0, 6.5, ), audio_now_s=7.0)
    detector.on_transcript(final(ME, "what batch size did you use", 10.4, 12.9), audio_now_s=13.5)   # overlaps a them utterance starting at 10.0
    assert detector.last_turn(ME, ended_before_s=10.0) == before
    assert detector.last_turn(ME).text == "what batch size did you use"
