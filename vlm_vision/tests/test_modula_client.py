import pytest
import httpx
from unittest.mock import patch, MagicMock
from local_agent.modula_client import ModulaClient
from local_agent.models import PickOrder


BASE_URL = "http://modula-wms.local:8080"


def test_fetch_active_order_returns_pick_order():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "order_id": "PO-2847",
        "sku": "STL-P-100-BK",
        "qty": 2,
        "tray_id": "T-0042",
    }

    with patch("local_agent.modula_client.httpx.get", return_value=mock_response):
        client = ModulaClient(base_url=BASE_URL)
        order = client.fetch_active_order(bay_id=1)

    assert isinstance(order, PickOrder)
    assert order.order_id == "PO-2847"
    assert order.sku == "STL-P-100-BK"
    assert order.qty == 2
    assert order.tray_id == "T-0042"


def test_fetch_active_order_returns_none_when_no_order():
    mock_response = MagicMock()
    mock_response.status_code = 204

    with patch("local_agent.modula_client.httpx.get", return_value=mock_response):
        client = ModulaClient(base_url=BASE_URL)
        order = client.fetch_active_order(bay_id=1)

    assert order is None


def test_confirm_pick_calls_correct_endpoint():
    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("local_agent.modula_client.httpx.post", return_value=mock_response) as mock_post:
        client = ModulaClient(base_url=BASE_URL)
        client.confirm_pick(order_id="PO-2847", result="correct")

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert "PO-2847" in str(call_kwargs)
