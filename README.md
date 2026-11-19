# amalgame-oncall

On-call paging for Amalgame : who is on call, how an incident reaches
them, and **the proof that it did**.

Sending a notification proves nothing : push services delay or drop
messages, phones in battery saving hold them, subscriptions die without
a word. Here the proof of reach is the take-over :

- **Escalation until someone takes the incident** : steps (after how
  long, to whom — a role of the rota or a login —, by push, SMS and/or
  mail).
- **Delivery receipt per push** : the phone's service worker sends the
  push id back when the notification arrives. A push not received within
  `fallback_s` goes again **by SMS and mail to the same person, at once**,
  without waiting for the next step. A person without a working device
  gets the SMS straight away.
- **Take it from the lock screen** : every alarm push carries a signed
  take token (HMAC-SHA-256 ; one person, one incident, 6 h). The
  "take it" button posts it : no login at 3 a.m. The caller checks it
  (`Pager.Verify`) and records the take-over.
- **The paged are told who took it** : the alarm on their phones is
  replaced (same tag) by "taken by …".
- **Phones are tested** every `test_every_s` (on call and backup) : a
  test push that does not come back is reported (`test-failed`) and the
  person told by SMS. A dead subscription is known the same day, not
  during an incident ; a subscription the push service dropped (404/410)
  is reported (`device-expired`).
- **Only the browsers' push services** are accepted as endpoints (FCM,
  Mozilla, Apple, Windows) : the server POSTs to the endpoint, a free one
  would let any user make it call an internal address.

Storage-agnostic : the caller passes its open incidents to `Tick` every
few seconds, its devices to `AddDevice`, and journals what `Drain`
returns ; after a restart, `Restore` replays what the journal says was
sent.

```amalgame
import Amalgame.OnCall

let policy: OnCallPolicy = OnCallPolicy.Parse(File_ReadAll("oncall.json"))   // policy.Errors
let pager: Pager = new Pager(policy, vapidKeyPem, vapidPubB64, "mailto:ops@example.com", secret, nowMs)
pager.AddDevice("karim", endpoint, p256dh, auth, "Fairphone", nowMs)        // from the phone's subscription

// every 2 s :
let inc: Incident = new Incident("site|rule|since", "crit", "Pump P2 tripped.", "North station · since 10:02", "/app.html#p2", startMs)
pager.Tick(incidents, nowMs)                 // inc.TakenBy = "karim" once taken
for e in pager.Drain() { journal(e.Kind, e.Key, e.Login, e.Detail) }

// routes :
pager.Receipt(id, nowMs)                     // POST rx    {id}    from the service worker
let t: TakeResult = pager.Verify(token, nowMs)   // POST take {token} : t.Ok, t.Login, t.Key
pager.Test("karim", nowMs)                   // "test my phone"
```

## Policy

```json
{
  "levels": ["crit"],
  "steps": [
    {"after_s": 0,    "to": "oncall",  "via": ["push"]},
    {"after_s": 300,  "to": "oncall",  "via": ["push", "sms"]},
    {"after_s": 600,  "to": "backup",  "via": ["push", "sms", "mail"]},
    {"after_s": 1200, "to": "manager", "via": ["sms", "mail"]}
  ],
  "fallback_s": 60,
  "test_every_s": 86400,
  "rota": [{"from": "2026-11-16T07:00:00Z", "oncall": "karim", "backup": "marie", "manager": "paul"}],
  "contacts": {"karim": {"phone": "06 12 34 56 78", "email": "karim@example.com"}},
  "country": "33",
  "public_url": "https://scada.example:8765",
  "sms_prefix": "Kairos",
  "sms": {"kind": "sms-gate", "url": "http://127.0.0.1:8080", "user": "sms", "password": "..."},
  "smtp": {"host": "ssl0.example.net", "port": 465, "user": "...", "password": "...", "from": "oncall@example.com"}
}
```

The rota entry in force is the last one whose `from` (RFC 3339 UTC) is
past. `sms.kind` : `sms-gate` (SMS Gateway for Android : a phone and its
SIM, see [amalgame-net-sms](https://github.com/amalgame-lang/amalgame-net-sms)),
`twilio` (`sid`, `token`, `from`) or `template` (`method`, `url`,
`content_type`, `body` with `{to}` `{text}` `{from}`, `user`, `password`).
SMS are transliterated to GSM 7-bit and cut to one SMS. Mail : SMTPS
(implicit TLS) through amalgame-net-smtp. A channel that cannot be used
(no gateway, no number) is still an event, with its reason : never
silent.

## Events (`Drain`)

| Kind | Detail |
|---|---|
| `page` | one send : `step`, `to`, `via` (push, sms, mail), `ok`, `code`, `fallback`, `device` / `phone` / `email`, `id`, `error` |
| `rx` | a push arrived : `id`, `device`, `after_ms` |
| `taken` | the paged were told who took it : `by`, `told` |
| `device-expired` | the push service dropped a subscription (404/410) : delete it |
| `test`, `test-ok`, `test-failed` | phone tests |

## The phone

`web/oncall-sw.js` is the service worker : delivery receipt, the
notification (an alarm stays until touched, vibrates, replaces the
previous one of the same incident), "take it" and "open", renewal of a
subscription (`pushsubscriptionchange`). Serve it from the app's origin
over HTTPS, register it with `?sub=<subscribe URL>`. Payload labels
(`takeLabel`, `openLabel`) and the take answer (`{title, body}`) come
from the server : the language is the app's. iOS (16.4+, app installed
on the home screen) shows no buttons : touching opens the page.

## Tests

```bash
./tests/run_am_tests.sh [amc]      # python3 + cryptography, openssl
```

41 checks over a whole escalation with simulated time, against stand-in
services (`tests/fake_services.py`) : a push service that **checks the
VAPID signature and decrypts every push with the phone's private key**
(RFC 8291), and an SMS gateway. Policy errors, rota, refused endpoints,
step 0, dropped subscription, SMS fallback for a push not received,
receipt with its delay, take tokens (valid, forged login, expired,
another server's secret), take-over and the paged told, no escalation
after it, a full escalation to the manager, restart without paging
again, phone tests (failed with SMS, confirmed, periodic).

## Dependencies

amalgame-net-webpush (≥ 0.1.2), amalgame-net-sms, amalgame-net-smtp,
amalgame-crypto, amalgame-threading, amalgame-datetime. Pure Amalgame.
Apache-2.0.
