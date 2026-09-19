# StreamHub 测试：每流单调 seq、环形缓冲封顶、Last-Event-ID 重放、订阅扇出与计数。

from __future__ import annotations

from app.frames import StatusFrame
from app.hub import StreamHub


def _frame(detail: str = "x"):
    return StatusFrame("XAUUSD", "4h", "open", detail)


def test_publish_assigns_monotonic_seq_per_stream():
    hub = StreamHub()
    key = ("XAUUSD", "4h", "original")

    assert hub.publish(key, _frame()) == 1
    assert hub.publish(key, _frame()) == 2
    # 不同流独立计数
    assert hub.publish(("BTCUSD", "4h", "original"), _frame()) == 1
    assert hub.last_seq(key) == 2


def test_ring_buffer_caps_entries():
    hub = StreamHub(ring_size=3)
    key = ("XAUUSD", "4h", "original")
    for i in range(5):
        hub.publish(key, _frame(str(i)))

    entries = hub.replay(key, 0)
    assert [e.seq for e in entries] == [3, 4, 5]
    assert [e.frame.detail for e in entries] == ["2", "3", "4"]


def test_replay_after_last_event_id():
    hub = StreamHub(ring_size=10)
    key = ("XAUUSD", "4h", "original")
    for _ in range(4):
        hub.publish(key, _frame())

    entries = hub.replay(key, 2)
    assert [e.seq for e in entries] == [3, 4]


def test_replay_from_current_position_returns_empty():
    hub = StreamHub()
    key = ("XAUUSD", "4h", "original")
    hub.publish(key, _frame())

    assert hub.replay(key, None) == []


def test_subscriber_fanout_and_unregister():
    hub = StreamHub()
    key = ("XAUUSD", "4h", "original")
    queue_a = hub.register(key)
    queue_b = hub.register(key)

    hub.publish(key, _frame())
    assert queue_a.qsize() == 1
    assert queue_b.qsize() == 1
    assert hub.subscriber_count(key) == 2

    hub.unregister(key, queue_a)
    assert hub.subscriber_count(key) == 1
    hub.publish(key, _frame())
    assert queue_a.qsize() == 1
    assert queue_b.qsize() == 2

    hub.unregister(key, queue_a)  # 幂等
    hub.unregister(key, queue_b)
    assert hub.subscriber_count(key) == 0


def test_snapshot_frame_payload_shape():
    from app.frames import Bar, SnapshotFrame, frame_payload

    frame = SnapshotFrame("XAUUSD", "4h", (Bar(1000, 1, 2, 0.5, 1.5, 10, 0),))
    payload = frame_payload(frame)
    assert payload["type"] == "snapshot"
    assert payload["symbol"] == "XAUUSD"
    assert payload["period"] == "4h"
    assert payload["bars"][0]["timestamp"] == 1000
    assert payload["bars"][0]["close"] == 1.5
