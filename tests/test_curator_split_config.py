from types import SimpleNamespace
from unittest.mock import MagicMock

from memorycore.storage.curator_llm import report


def _memory() -> dict:
    return {
        "id": "memory-1",
        "title": "Compound memory",
        "content": "x" * 300,
        "type": "project_memory",
    }


def _prepare(monkeypatch) -> MagicMock:
    detector = MagicMock(return_value=[{"action": "split", "id": "memory-1"}])
    monkeypatch.setattr(report, "_load_extraction_config", lambda _: SimpleNamespace(temperature=0.0))
    monkeypatch.setattr(report, "_get_vector_store", lambda _: SimpleNamespace(available=False))
    monkeypatch.setattr(report, "_fetch_active_memories", lambda _: [_memory()])
    monkeypatch.setattr(report, "_cleanup_reviewed_ids", lambda: None)
    monkeypatch.setattr(report, "_mark_reviewed", lambda *_, **__: None)
    monkeypatch.setattr(report, "_llm_detect_splittable", detector)
    return detector


def test_split_detection_is_disabled_by_default(monkeypatch):
    detector = _prepare(monkeypatch)

    result = report.llm_curator_report(config={"llm_curator": {}})

    assert result["split_candidates"] == []
    assert result["diagnostics"]["split_candidates_checked"] == 0
    detector.assert_not_called()


def test_split_detection_requires_explicit_opt_in(monkeypatch):
    detector = _prepare(monkeypatch)

    result = report.llm_curator_report(config={
        "llm_curator": {
            "split_enabled": True,
            "split_content_threshold": 200,
        }
    })

    assert result["split_candidates"] == [{"action": "split", "id": "memory-1"}]
    assert result["diagnostics"]["split_candidates_checked"] == 1
    detector.assert_called_once()
