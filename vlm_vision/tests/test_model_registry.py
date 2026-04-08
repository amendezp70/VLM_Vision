# vlm_vision/tests/test_model_registry.py
import os
import pytest
from unittest.mock import MagicMock
from local_agent.model_registry import ModelRegistry


@pytest.fixture
def registry(tmp_path):
    client = MagicMock()
    return ModelRegistry(
        cloud_client=client,
        model_dir=str(tmp_path),
        current_model_path=str(tmp_path / "current.onnx"),
    )


def test_no_update_when_cloud_returns_none(registry):
    registry._client.check_model_version.return_value = None
    result = registry.check_and_update()
    assert result is None
    registry._client.download_model.assert_not_called()


def test_no_update_when_version_matches(registry):
    registry._current_version = "v3"
    registry._client.check_model_version.return_value = {"version": "v3", "url": "http://x/m.onnx"}
    result = registry.check_and_update()
    assert result is None
    registry._client.download_model.assert_not_called()


def test_downloads_new_model_when_version_differs(registry):
    registry._current_version = "v2"
    registry._client.check_model_version.return_value = {"version": "v3", "url": "http://x/m.onnx"}
    registry._client.download_model.return_value = True

    result = registry.check_and_update()

    assert result is not None
    assert result.endswith(".onnx")
    registry._client.download_model.assert_called_once()
    assert registry._current_version == "v3"


def test_returns_none_when_download_fails(registry):
    registry._current_version = "v2"
    registry._client.check_model_version.return_value = {"version": "v3", "url": "http://x/m.onnx"}
    registry._client.download_model.return_value = False

    result = registry.check_and_update()

    assert result is None
    assert registry._current_version == "v2"


def test_first_check_with_no_prior_version(registry):
    registry._current_version = None
    registry._client.check_model_version.return_value = {"version": "v1", "url": "http://x/m.onnx"}
    registry._client.download_model.return_value = True

    result = registry.check_and_update()

    assert result is not None
    assert registry._current_version == "v1"
