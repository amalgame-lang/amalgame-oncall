# Changelog

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
