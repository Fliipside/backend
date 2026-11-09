from app.schemas.voice import VoiceAnalysisResult
from app.services.voice import label_speakers_without_me, speaker_letters


def make_result(speakers: list[str], utterances: list[tuple[float, str]]) -> VoiceAnalysisResult:
    return VoiceAnalysisResult.model_validate({
        "speakers": [
            {"speaker": name, "role": "unknown", "speech_seconds": 1.0}
            for name in speakers
        ],
        "utterances": [
            {"start": start, "end": start + 1, "speaker": name, "role": "unknown", "text": name}
            for start, name in utterances
        ],
    })


def test_speaker_letters_continue_after_z() -> None:
    assert [speaker_letters(i) for i in (0, 1, 25, 26, 27, 51, 52)] == [
        "A", "B", "Z", "AA", "AB", "AZ", "BA",
    ]


def test_without_me_labels_speakers_by_first_utterance() -> None:
    result = make_result(
        speakers=["speaker_2", "speaker_1", "speaker_3"],
        utterances=[(5.0, "speaker_2"), (0.0, "speaker_1"), (9.0, "speaker_3"), (12.0, "speaker_1")],
    )

    labeled = label_speakers_without_me(result)

    assert [s.speaker for s in labeled.speakers] == ["A", "B", "C"]
    assert [u.speaker for u in labeled.utterances] == ["B", "A", "C", "A"]
    assert [u.text for u in labeled.utterances] == ["speaker_2", "speaker_1", "speaker_3", "speaker_1"]


def test_speaker_without_utterances_comes_last() -> None:
    result = make_result(
        speakers=["silent", "speaker_1"],
        utterances=[(0.0, "speaker_1")],
    )

    labeled = label_speakers_without_me(result)

    assert [s.speaker for s in labeled.speakers] == ["A", "B"]
    assert labeled.speakers[1].speech_seconds == 1.0


def test_result_with_me_is_unchanged() -> None:
    result = make_result(
        speakers=["me", "speaker_1"],
        utterances=[(0.0, "speaker_1"), (1.0, "me")],
    )

    assert label_speakers_without_me(result) == result
