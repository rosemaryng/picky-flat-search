# PayPal sandbox setup runbook

The dashboard takes real money for "Pro" via PayPal. It runs in **three modes**:

| Mode | When | What happens |
|------|------|--------------|
| **Simulated** (default) | no keys set | Deterministic `SIM-…` / `SIMSUB-…` objects; the demo "earns" with zero setup. |
| **Sandbox** | sandbox keys set | Real PayPal REST calls against `api-m.sandbox.paypal.com` with test accounts. |
| **Live** | live keys + `PAYPAL_BASE` | Real money. Only flip this on intentionally. |

The golden rule everywhere: **revenue is recorded only once payment has settled** —
a one-off order capture is `COMPLETED`, or a subscription is `ACTIVE`. These are the
[`paypal.is_completed`](../payments/paypal.py) / `paypal.is_active` predicates; never
re-check the raw status string at a call site.

## 1. Run with zero keys (simulated)

```bash
python -m web.app          # http://localhost:5000
```

- **Upgrade to Pro — £9.99** → `/simulate-payment` runs `create_order` → `capture_order`
  inline. The simulated capture returns `COMPLETED`, so revenue ticks up by £9.99.
- **Subscribe £9.99/mo** → `/upgrade?plan=subscription` returns a simulated
  `SIMSUB-…` whose `get_subscription` reports `ACTIVE`.

No external calls are made; this is what CI and the offline demo use.

## 2. Get PayPal sandbox credentials

1. Sign in at <https://developer.paypal.com/dashboard/> with a PayPal account.
2. **Apps & Credentials → Sandbox → Create App** (e.g. `flat-finder`). PayPal
   auto-creates sandbox business + personal test accounts under
   **Testing Tools → Sandbox Accounts**.
3. Copy the app's **Client ID** and **Secret**.

## 3. Configure the environment

```bash
export PAYPAL_CLIENT_ID="<sandbox client id>"
export PAYPAL_SECRET="<sandbox secret>"
# Optional — defaults to the sandbox base:
export PAYPAL_BASE="https://api-m.sandbox.paypal.com"
```

`flatfinder.config.has_paypal()` returns `True` once both `PAYPAL_CLIENT_ID` and
`PAYPAL_SECRET` are present; that flips the helper from simulated to real REST calls.

> **Never commit these.** Use a local `.env`/shell export or your secrets manager.

### One-off vs subscription

- **One-off order** needs no extra config — `create_order` posts to
  `/v2/checkout/orders` with `intent=CAPTURE`.
- **Subscription** needs a billing **plan id**. Create a product + plan once via the
  [Catalog Products](https://developer.paypal.com/docs/api/catalog-products/v1/) and
  [Billing Plans](https://developer.paypal.com/docs/api/subscriptions/v1/) APIs, then
  pass it: `paypal.create_subscription(plan_id="P-XXXXXXXX")`. With no `plan_id` the
  helper falls back to the simulated `SIMSUB-…` flow even when keys are present.

## 4. The checkout flow

```
create_order ──> approve_url ──> buyer approves ──> /paypal/return?token=<id>
                                                        └─> capture_order ──> is_completed? ──> record "paid"

create_subscription ──> approve_url ──> buyer approves ──> /paypal/return?subscription_id=<id>
                                                              └─> get_subscription ──> is_active? ──> record "paid"
```

`/paypal/return` records the payment with `status="paid"` **only** when the settlement
predicate is true; otherwise it stores the raw status (e.g. `PENDING`) and revenue
ignores it.

## 5. Test the sandbox end-to-end

1. Start the app with the sandbox keys exported.
2. Click **Upgrade to Pro** (one-off) or **Subscribe** (recurring) → you're redirected
   to PayPal's sandbox approval page.
3. Log in with the **personal** sandbox account (Sandbox Accounts → personal account
   email + system-generated password).
4. Approve → PayPal redirects back to `/paypal/return`, the order is captured /
   subscription confirmed, and **revenue** updates on the dashboard.
5. Verify the money in the **business** sandbox account's activity.

## 6. Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| Revenue stays £0 after approving | Capture not `COMPLETED` / subscription not `ACTIVE` yet — by design it isn't counted until settled. |
| Redirected to `sandbox.paypal.com` but get `SIM-…` ids | Keys not actually exported in the process running Flask. Check `has_paypal()`. |
| `KeyError: access_token` | Wrong client id/secret, or hitting live base with sandbox creds. |
| Subscription always simulated | No `plan_id` passed — create a billing plan and pass it to `create_subscription`. |

## 7. Tests

`tests/test_payments.py` mocks all HTTP (`post_json` / `post_form` / `get_json`) and
the `has_paypal` flag, so it runs offline. It asserts the simulated fallback shapes,
the real REST request bodies, and — crucially — that revenue is counted **only** for
`COMPLETED` captures and `ACTIVE` subscriptions:

```bash
ruff check .
python -m pytest -q
```
