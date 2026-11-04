"""The local speech-to-text adapter against the SpeechToText contract, on real audio."""

from app.adapters.factory import make_speech_to_text
from app.config import settings
from tests.contract.speech_to_text_contract import SpeechToTextContract


class TestMlxWhisperSpeechToText(SpeechToTextContract):
    def make_adapter(self):
        assert settings.stt_provider == "local"
        return make_speech_to_text()
