# LIKI operator UI

The operator console is served at `/` by `liki.server` and uses only the same-origin external assets `liki/web/styles.css` and `liki/web/app.js`. It is an authenticated, read-only projection of the control plane except for the explicitly risk-reducing paper emergency-stop request.

## Session handling

An operator enters a bearer token in a password input. JavaScript holds the token only in its module memory for the active page, clears the input after connecting, and discards the token and rendered projection state on sign out. No browser persistence API is used. Every data request sends `Authorization: Bearer <token>` to the same origin.

The console deliberately renders all returned values as text nodes. It selects only operational fields from each response and does not render raw artifact contents, sealed evidence, or opaque proposal packages. Network, authorization, empty, and partial-projection states are explicitly identified rather than replaced with example metrics.

## Views and API contract

| View | Authenticated endpoint(s) | Displayed projection |
| --- | --- | --- |
| Status | `GET /status`, `GET /incidents` | mode, database state, acceptance state, aggregate counts, and unresolved incident records |
| Active runs | `GET /scheduler/why-running` | scheduler activity state, active action, reason, heartbeat, lease, and retry count |
| Queues | `GET /scheduler/queues` | task class/lane/status grouped queue counts and oldest timestamp |
| Campaigns | `GET /campaigns` | campaign purpose, horizon, and declared/allocated budgets |
| Paper | `GET /paper/status`, `GET /paper/orders`, `GET /risk/reservations` | paper run, active stop, order, and risk-reservation projections |
| Governance | `GET /governance/proposals` | proposal status and approval snapshot reference |
| Requirements | `GET /requirements` | SRS version, coverage counts, requirement/module/test traceability references |

The USD 10,000/week business milestone is intentionally shown as unavailable: the currently exposed API contract does not provide the required net PnL, capital, risk, capacity, or uncertainty fields. The console never derives it from unrelated records.

## Safety controls

The persistent header states that real-money execution is prohibited. The Paper view repeats this restriction and has no order-entry or live-execution controls.

Only a role reported as `owner` or `operator` by `GET /status` sees the emergency-stop control. The control requires selecting a real returned paper run, entering a reason, confirming the safety action, and uses `POST /paper/emergency-stop` with:

```text
Authorization: Bearer <active page token>
Idempotency-Key: <fresh UUID>
Content-Type: application/json

{"run_id":"<selected paper run>","reason":"<operator-entered reason>"}
```

The server remains the authorization authority. The UI renders completion or failure feedback and refreshes the paper projection after a successful request. The current server contract requires `run_id`; if a later server change makes global stops run-independent, the UI contract must be updated with that server change rather than guessing a body shape.

## SRS alignment and endpoint gaps

This UI implements Phase 10's evidence-backed, deterministic status projection and supports Sections 29.5 (truthful scheduler activity), 30.3/30.10 (token and data non-disclosure), 31 (honest observability), 37 (authenticated operations/paper endpoints), and the real-money prohibition.

Section 31 metrics such as inference/provider economics, statistical distributions, execution deviation, and system SLO compliance cannot be displayed until their authenticated read models are implemented. Likewise, current endpoints do not expose the data required by the full Section 25.2A milestone convention. These are server/API surface gaps, not values the UI may invent.
