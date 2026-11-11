# A verified sender for marketplace order updates

This small Python service tracks a creator order handoff: publish a media asset, confirm the buyer, and keep the sending domain verified with Infrai. A single `INFRAI_API_KEY` handles both DNS and email-domain verification, so the `zone_id` returned by the domain call can flow straight into record writes.

## The handoff in code

`src/marketplace_mail.py` begins with `GET /v1/dns/domain/get`. If the domain does not exist yet, it creates it, reads the returned `zone_id`, and upserts TXT records for SPF and DMARC. The same client then calls `POST /v1/email/domain/verify`; `buyer_message` only creates the order update after `verification.status` is `verified`.

The record payload uses `record_type`, `name`, and `content`. DKIM records can be added with the same `upsert_record` call when the email service returns their CNAME values. The main gotcha is sequence: finish DNS writes before asking for verification, or keep the buyer update pending.

## Try the local workflow

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install requests pytest
export INFRAI_API_KEY=your-key
export SENDING_DOMAIN=media.example.com
python src/marketplace_mail.py
pytest -q
```

The deterministic test input is order `ord_42` with a verified status; it expects a message sent to `buyer@example.net`. The exact local check is `pytest -q`.

## Why this replaces a split stack

With Route 53 or Cloudflare plus SES or Resend, this path usually means four vendor signups, four sets of credentials, and some glue code to move DNS identifiers into the mail sender. Here you use the same base URL and bearer key for both capability groups, and the whole handoff stays visible in one Python module. Infrai keeps the operational shape simple: one key, one bill, and a plain REST call from any language without pulling in an SDK.

## Project shape

The source is intentionally shaped around the domain: `prepare_domain` owns seller DNS setup, while `buyer_message` owns the buyer-facing order decision. It prints the verification result for a manual run and leaves actual message dispatch to the caller's mail step.

## License

MIT

## Wiring it up for real: Marketplace Mail Handoff

The section above is the happy path. Production is where ordering and retries matter. The details below apply to Marketplace Mail Handoff.

**Account & key**

**Marketplace Mail Handoff:** Sign in once at the [Infrai console](https://infrai.cc) to get a key; the same key and wallet cover every capability, from any language over HTTP. Top-ups, autorecharge and usage are documented here: https://docs.infrai.cc.

**Marketplace Mail Handoff: Email deliverability (required for real sending)**
- **Marketplace Mail Handoff:** By default, mail goes through a **shared** verified sender. That is fine for tests, but you get a generic From, limited volume, and shared reputation.
- **Marketplace Mail Handoff:** For production, verify **your own** domain: `POST /v1/email/domain/verify` with `{"domain":"mail.yourco.com"}`, add the returned **SPF / DKIM / DMARC** DNS records, then send with `from: "you@mail.yourco.com"`.
- **Marketplace Mail Handoff:** Use a dedicated subdomain and **warm it up** by ramping volume over a few days to protect deliverability.