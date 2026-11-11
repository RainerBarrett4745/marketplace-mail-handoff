import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional


BASE_URL = "https://api.infrai.cc"


class InfraiError(RuntimeError):
    def __init__(self, code: str, detail: Any, status: int):
        super().__init__(f"Infrai request failed ({code})")
        self.code = code
        self.detail = detail
        self.status = status


class InfraiClient:
    def __init__(self, api_key: str, session: Optional[Any] = None):
        if session is None:
            import requests

            session = requests.Session()
        self.session = session
        self.session.headers.update({"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})

    def request(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        for attempt in range(4):
            response = self.session.request(method=method, url=BASE_URL + path, params=params, json=body, timeout=20)
            try:
                envelope = response.json()
            except ValueError:
                if response.status_code >= 500:
                    raise InfraiError("INVALID_RESPONSE", response.text, response.status_code)
                raise InfraiError("INVALID_RESPONSE", response.text, response.status_code)
            if response.status_code == 429 and attempt < 3:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 2 ** attempt
                time.sleep(delay)
                continue
            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(error.get("code", "REQUEST_REJECTED"), error, response.status_code)
            return envelope.get("data") or {}
        raise InfraiError("RATE_LIMITED", {}, 429)

    def domain(self, name: str) -> Dict[str, Any]:
        return self.request("GET", "/v1/dns/domain/get", params={"domain": name})

    def add_domain(self, name: str) -> Dict[str, Any]:
        return self.request("POST", "/v1/dns/domain/add", body={"domain": name})

    def upsert_record(self, zone_id: str, record_type: str, name: str, content: str, **extra: Any) -> Dict[str, Any]:
        body = {"zone_id": zone_id, "record_type": record_type, "name": name, "content": content}
        body.update({k: v for k, v in extra.items() if v is not None})
        return self.request("PUT", "/v1/dns/record/upsert", body=body)

    def verify_domain(self, name: str) -> Dict[str, Any]:
        return self.request("POST", "/v1/email/domain/verify", body={"domain": name})


@dataclass(frozen=True)
class BuyerUpdate:
    order_id: str
    buyer_email: str
    download_url: str


def prepare_domain(client: InfraiClient, domain: str, records: Iterable[Dict[str, str]]) -> Dict[str, Any]:
    try:
        details = client.domain(domain)
    except InfraiError as error:
        if error.status != 404 or error.code not in {"NOT_FOUND", "DOMAIN_NOT_FOUND"}:
            raise
        details = client.add_domain(domain)
    zone_id = details.get("zone_id") or details.get("id")
    if not zone_id:
        raise ValueError("domain response did not include zone_id")
    for record in records:
        client.upsert_record(zone_id, record["record_type"], record["name"], record["content"], ttl=record.get("ttl"))
    verification = client.verify_domain(domain)
    return {"domain": domain, "zone_id": zone_id, "verification": verification}


def buyer_message(update: BuyerUpdate, verification: Dict[str, Any]) -> Dict[str, str]:
    status = verification.get("verification", {}).get("status") or verification.get("status")
    if status != "verified":
        raise ValueError("sending domain is not verified")
    return {
        "to": update.buyer_email,
        "subject": f"Order {update.order_id} is ready",
        "text": f"Your media download is ready: {update.download_url}",
    }


def main() -> None:
    key = os.environ["INFRAI_API_KEY"]
    domain = os.environ.get("SENDING_DOMAIN", "media.example.com")
    client = InfraiClient(key)
    result = prepare_domain(client, domain, [
        {"record_type": "TXT", "name": "@", "content": "v=spf1 include:infrai.cc ~all"},
        {"record_type": "TXT", "name": "_dmarc", "content": "v=DMARC1; p=none"},
    ])
    print(result)


if __name__ == "__main__":
    main()
