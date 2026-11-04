import time
import wave
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import main
from app.audio.frames import FRAME_BYTES
from app.audio.replay import frames_at_real_time, replay_files, resolve
from app.main import app
from app.ports import Profile
from tests.fakes import CannedLLM, CONFIRMING_REPLY, InMemoryStore, SilentSpeechToText


def write_stereo(path: Path, seconds: float):
    samples = np.zeros(int(16000 * seconds) * 2, dtype=np.int16)
    samples[1::2] = 3000   # something on the them channel
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(samples.tobytes())


def test_only_wav_files_inside_the_folder_resolve(tmp_path):
    write_stereo(tmp_path / "meeting.wav", 0.5)
    (tmp_path / "notes.txt").write_text("x")
    with wave.open(str(tmp_path / "mono.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\x00" * 3200)
    assert replay_files(tmp_path) == ["meeting.wav"], "the mono file is not playable and stays unlisted"
    assert resolve(tmp_path, "meeting.wav") == tmp_path / "meeting.wav"
    assert resolve(tmp_path, "../../etc/meeting.wav") == tmp_path / "meeting.wav", "only the bare name counts"
    with pytest.raises(FileNotFoundError):
        resolve(tmp_path, "notes.txt")
    with pytest.raises(FileNotFoundError):
        resolve(tmp_path, "missing.wav")


async def test_frames_come_out_whole_and_paced(tmp_path):
    write_stereo(tmp_path / "meeting.wav", 0.5)
    started = time.perf_counter()
    frames = [frame async for frame in frames_at_real_time(tmp_path / "meeting.wav")]
    elapsed = time.perf_counter() - started
    assert len(frames) == 5 and all(len(f) == FRAME_BYTES for f in frames)
    assert 0.35 <= elapsed <= 0.8, "five frames of 100 ms take about half a second"


def test_a_replayed_session_runs_and_stops_by_itself(tmp_path, monkeypatch):
    write_stereo(tmp_path / "meeting.wav", 1.0)
    monkeypatch.setattr(main.settings, "replay_dir", str(tmp_path))
    monkeypatch.setattr(main, "make_speech_to_text", SilentSpeechToText)
    monkeypatch.setattr(main, "llm", CannedLLM(CONFIRMING_REPLY))
    store = InMemoryStore()
    store.profiles["local"] = Profile("local", "Surya", [], "", [], "", "", 1)
    monkeypatch.setattr(main, "store", store)

    client = TestClient(app)
    assert client.get("/api/replays").json() == {"files": ["meeting.wav"]}
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "start", "replay_file": "meeting.wav"})
        events = [ws.receive_json()]
        while events[-1]["type"] != "stopped":
            events.append(ws.receive_json())
    kinds = [e["type"] for e in events]
    assert kinds[0] == "started" and kinds[-1] == "stopped"
    assert kinds.count("stats") == 1
    assert events[-1]["frames"] == 10

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "start", "replay_file": "nope.wav"})
        assert "no replay file" in ws.receive_json()["message"]
