import pytest
import math
from memorycore.storage.search import _cluster_similar_records

class DummyPoint:
    def __init__(self, id, vector):
        self.id = id
        self.vector = vector

class DummyClient:
    def __init__(self, points):
        self.points = points

    def retrieve(self, collection_name, ids, with_vectors, with_payload):
        return [p for p in self.points if p.id in ids]

class DummyVS:
    def __init__(self, points):
        self._client = DummyClient(points)
        self.config = type("Config", (), {"collection": "test"})()

def test_cluster_similar_records_basic():
    # V1 and V2 are similar, V3 is different
    p1 = DummyPoint("A", [1.0, 0.0, 0.0])
    p2 = DummyPoint("B", [0.9, 0.1, 0.0])  # cos sim ~ 0.99
    p3 = DummyPoint("C", [0.0, 1.0, 0.0])  # cos sim 0.0

    vs = DummyVS([p1, p2, p3])
    records = [
        {"id": "A", "title": "rec A"},
        {"id": "B", "title": "rec B"},
        {"id": "C", "title": "rec C"},
    ]

    clustered, count, groups = _cluster_similar_records(vs, records, threshold=0.85)

    assert len(clustered) == 2
    assert clustered[0]["id"] == "A"
    assert clustered[0]["_clustered_ids"] == ["B"]
    assert clustered[1]["id"] == "C"
    assert "_clustered_ids" not in clustered[1]

    assert count == 1
    assert groups == 1

def test_cluster_similar_records_empty_and_fallback():
    # empty records
    vs = DummyVS([])
    clustered, count, groups = _cluster_similar_records(vs, [], 0.85)
    assert len(clustered) == 0
    assert count == 0

    # no client
    vs_no_client = type("VS", (), {})()
    records = [{"id": "A"}]
    clustered, count, groups = _cluster_similar_records(vs_no_client, records, 0.85)
    assert len(clustered) == 1
    assert count == 0

def test_cluster_similar_records_all_similar():
    points = [
        DummyPoint("1", [1.0, 0.0]),
        DummyPoint("2", [1.0, 0.0]),
        DummyPoint("3", [1.0, 0.0]),
        DummyPoint("4", [1.0, 0.0]),
    ]
    vs = DummyVS(points)
    records = [{"id": str(i)} for i in range(1, 5)]

    clustered, count, groups = _cluster_similar_records(vs, records, threshold=0.99)
    assert len(clustered) == 1
    assert clustered[0]["id"] == "1"
    assert set(clustered[0]["_clustered_ids"]) == {"2", "3", "4"}
    assert count == 3
    assert groups == 1

def test_cluster_similar_records_all_different():
    points = [
        DummyPoint("1", [1.0, 0.0, 0.0]),
        DummyPoint("2", [0.0, 1.0, 0.0]),
        DummyPoint("3", [0.0, 0.0, 1.0]),
    ]
    vs = DummyVS(points)
    records = [{"id": str(i)} for i in range(1, 4)]

    clustered, count, groups = _cluster_similar_records(vs, records, threshold=0.5)
    assert len(clustered) == 3
    assert count == 0
    assert groups == 0
