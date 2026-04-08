# vlm_vision/tests/test_cloud_sync_client.py
import json
import pytest
from unittest.mock import patch, MagicMock
from local_agent.cloud_sync_client import CloudSyncClient
from local_agent.models import PickEvent


def make_event(order_id="PO-001", result="correct") -> PickEvent:
    return PickEvent(
        order_id=order_id, sku="STL-P-100-BK", qty_picked=1,
        bay_id=1, worker_id="jmartinez", result=result,
        timestamp=1712500000.0,
    )


@patch("local_agent.cloud_sync_client.requests.post")
def test_push_picks_sends_post_with_events(mock_post):
    mock_post.return_value = MagicMock(status_code=200, json=lambda: {"ok": True})
    client = CloudSyncClient(base_url="http://catalyst.example.com")

    events = [make_event("PO-001"), make_event("PO-002")]
    result = client.push_picks(events)

    assert result is True
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert "/picks/sync" in call_args[0][0]
    body = call_args[1]["json"]
    assert len(body["events"]) == 2
    assert body["events"][0]["order_id"] == "PO-001"


@patch("local_agent.cloud_sync_client.requests.post")
def test_push_picks_returns_false_on_http_error(mock_post):
    mock_post.return_value = MagicMock(status_code=500)
    client = CloudSyncClient(base_url="http://catalyst.example.com")

    result = client.push_picks([make_event()])
    assert result is False


@patch("local_agent.cloud_sync_client.requests.post")
def test_push_picks_returns_false_on_network_error(mock_post):
    mock_post.side_effect = ConnectionError("offline")
    client = CloudSyncClient(base_url="http://catalyst.example.com")

    result = client.push_picks([make_event()])
    assert result is False


@patch("local_agent.cloud_sync_client.requests.post")
def test_push_picks_with_empty_list_is_noop(mock_post):
    client = CloudSyncClient(base_url="http://catalyst.example.com")
    result = client.push_picks([])
    assert result is True
    mock_post.assert_not_called()


@patch("local_agent.cloud_sync_client.requests.get")
def test_check_model_version_returns_version_string(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200, json=lambda: {"version": "v3", "url": "http://example.com/model.onnx"}
    )
    client = CloudSyncClient(base_url="http://catalyst.example.com")

    info = client.check_model_version()
    assert info["version"] == "v3"
    assert "url" in info


@patch("local_agent.cloud_sync_client.requests.get")
def test_check_model_version_returns_none_on_error(mock_get):
    mock_get.side_effect = ConnectionError("offline")
    client = CloudSyncClient(base_url="http://catalyst.example.com")

    info = client.check_model_version()
    assert info is None


@patch("local_agent.cloud_sync_client.requests.get")
def test_download_model_writes_file(mock_get, tmp_path):
    mock_get.return_value = MagicMock(
        status_code=200,
        iter_content=lambda chunk_size: [b"ONNX_DATA_CHUNK1", b"ONNX_DATA_CHUNK2"],
    )
    client = CloudSyncClient(base_url="http://catalyst.example.com")
    dest = tmp_path / "model.onnx"

    ok = client.download_model(url="http://example.com/model.onnx", dest=str(dest))
    assert ok is True
    assert dest.read_bytes() == b"ONNX_DATA_CHUNK1ONNX_DATA_CHUNK2"


@patch("local_agent.cloud_sync_client.requests.get")
def test_download_model_returns_false_on_error(mock_get, tmp_path):
    mock_get.side_effect = ConnectionError("offline")
    client = CloudSyncClient(base_url="http://catalyst.example.com")
    dest = tmp_path / "model.onnx"

    ok = client.download_model(url="http://example.com/model.onnx", dest=str(dest))
    assert ok is False
    assert not dest.exists()
