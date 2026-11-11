from unittest.mock import Mock

import pytest

from src.marketplace_mail import BuyerUpdate, InfraiClient, InfraiError, buyer_message, prepare_domain


def test_buyer_message_requires_verified_domain():
    update = BuyerUpdate("ord_42", "buyer@example.net", "https://cdn.example.net/file.zip")
    with pytest.raises(ValueError):
        buyer_message(update, {"status": "pending"})
    message = buyer_message(update, {"status": "verified"})
    assert message["to"] == "buyer@example.net"
    assert message["subject"] == "Order ord_42 is ready"


@pytest.mark.parametrize("code,status", [
    ("UNAUTHORIZED", 401), ("FORBIDDEN", 403), ("RATE_LIMITED", 429),
    ("VENDOR_DOWN", 503), ("INVALID_RESPONSE", 404), ("NOT_FOUND", 500),
])
def test_lookup_failures_do_not_create_domain(code, status):
    client = Mock()
    error = InfraiError(code, {}, status)
    client.domain.side_effect = error
    with pytest.raises(InfraiError) as caught:
        prepare_domain(client, "example.com", [])
    assert caught.value is error
    client.add_domain.assert_not_called()
    client.upsert_record.assert_not_called()
    client.verify_domain.assert_not_called()


@pytest.mark.parametrize("code", ["NOT_FOUND", "DOMAIN_NOT_FOUND"])
def test_missing_domain_is_created(code):
    client = Mock()
    client.domain.side_effect = InfraiError(code, {}, 404)
    client.add_domain.return_value = {"zone_id": "zone-1"}
    client.verify_domain.return_value = {"status": "pending"}
    result = prepare_domain(client, "example.com", [
        {"record_type": "TXT", "name": "@", "content": "test"},
    ])
    client.add_domain.assert_called_once_with("example.com")
    client.upsert_record.assert_called_once_with("zone-1", "TXT", "@", "test", ttl=None)
    assert result["zone_id"] == "zone-1"


def response(status, envelope, headers=None):
    return Mock(status_code=status, headers=headers or {}, json=Mock(return_value=envelope))


def test_failed_429_envelope_retries_before_rejecting(monkeypatch):
    sleep = Mock()
    monkeypatch.setattr("src.marketplace_mail.time.sleep", sleep)
    session = Mock()
    session.request.side_effect = [
        response(429, {"ok": False, "error": {"code": "RATE_LIMITED"}}, {"Retry-After": "0.25"}),
        response(200, {"ok": True, "data": {"zone_id": "zone-1"}}),
    ]
    assert InfraiClient("test", session).domain("example.com") == {"zone_id": "zone-1"}
    assert session.request.call_count == 2
    sleep.assert_called_once_with(0.25)


def test_rate_limit_retries_are_bounded(monkeypatch):
    sleep = Mock()
    monkeypatch.setattr("src.marketplace_mail.time.sleep", sleep)
    session = Mock()
    session.request.return_value = response(429, {"ok": False, "error": {"code": "RATE_LIMITED"}})
    with pytest.raises(InfraiError) as caught:
        InfraiClient("test", session).domain("example.com")
    assert caught.value.status == 429
    assert caught.value.code == "RATE_LIMITED"
    assert session.request.call_count == 4
    assert [call.args[0] for call in sleep.call_args_list] == [1, 2, 4]
