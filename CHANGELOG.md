# Changelog

## v0.2.1 — 2026-11-20

- `web/oncall-sw.js` : `h=<header>` in the registration URL, sent (value 1)
  when the worker posts a renewed subscription. An app that requires a
  header against cross-site requests refused the renewal : the phone
  stopped receiving alarms without anyone knowing.
- `Pager.Icon`, `Pager.Badge` : the notification's icon and status-bar
  badge, in every push.

## v0.2.0 — 2026-11-20

- SMS followed until delivered or failed (net-sms v0.2.0 `Status`) :
  events `sms-delivered`, `sms-sent`, `sms-failed` (with the phone's
  reason) ; an SMS the phone did not send within `fallback_s` is failed.
  A failed SMS (or one refused by the gateway) : mail to the same person
  if none went yet, and the next escalation step paged at once (`advance`),
  unless that person's push was received. Found with a real phone : the
  gateway accepted (202) while the phone lacked the SMS permission.
- `page` of an SMS : `state` (`accepted` / `failed`) and `tracked`.
- Tests : 51 checks.

## v0.1.0 — 2026-11-19

- `OnCallPolicy` : levels, escalation steps, rota with roles, contacts,
  SMS gateway, SMTP ; errors reported, not guessed.
- `Pager` : `Tick` (escalation, SMS + mail fallback for a push not
  received, the paged told who took it, periodic phone tests), `Receipt`,
  take tokens (`Token`, `Verify`), devices limited to the browsers' push
  services, `Drain` (events to journal), `Restore` after a restart.
- `web/oncall-sw.js` : the phone's service worker.
- Tests : 41 checks against a push service that checks VAPID and
  decrypts each push, and an SMS gateway.
