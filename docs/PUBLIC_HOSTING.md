# Public dashboard and operator access

User login is optional and off by default when no password has been configured. While off, anyone who can reach the application can change settings, read messages and use transmit controls. **Enable User login for unattended or public-facing instances** before making the application accessible. Use HTTPS or a trusted private VPN for remote access.

## First setup and lost passwords

Open **Settings → Security** and turn on **Enable User login**. Set and confirm a password of 6–256 characters in the browser prompt. Saving enables protection and signs in the current browser for one hour. Other browsers must sign in separately and receive read-only public data until they do. Cancel leaves login off. Signed-in users may disable login in Security, unlocking access for everyone who can reach the application.

No desktop or tray is required for initial setup on a headless Pi. Existing configured passwords retain protection on upgrade. For recovery, use **Set/reset operator password** in the host tray/Start menu, or the terminal command with the same service account and deployment paths. The standard Pi service command is:

```sh
cd /opt/aprs-propview
PROPVIEW_DATA_DIR=/opt/aprs-propview .venv/bin/python main.py --set-operator-password
```

Recovery enables login and revokes existing sessions. The old password cannot be retrieved. No hosted account or recovery service is needed.

The password window includes **Automatically sign in browsers opened by this
computer** (enabled by default). Startup, the tray's **Open PropView**, and
reopening the normal shortcut while PropView is running open that computer's
browser with a single-use capability that expires after 90 seconds. The
capability travels in a URL fragment, is immediately removed, and can be
exchanged only once, at its intended origin, for an 8-hour browser session.
No public HTTP endpoint returns a local login token. A protected local launcher file
lets the ordinary shortcut ask the existing backend to open its own browser;
the HTTP response never contains a login token or operator session.

Remote browsers still need their own password login. Typing the address manually
in another browser does not automatically sign it in. Opening the host app does
not grant access to any public viewers or to other browser profiles.

The credential verifier is stored as `operator-auth.json` beside the active
configuration, separate from settings exports/imports. Only a salted PBKDF2-SHA256 verifier is saved. Restrict access
to that directory to trusted host users. Back up the verifier separately if
desired; it is deliberately excluded from Git and Docker build contexts.

Resetting the password revokes all sessions, including sessions on a running
backend. A corrupt verifier, or a verifier removed while protected mode is running, leaves operator functions locked. A new installation without credentials defaults to login off. The
unauthenticated visitor cannot reset an enabled password. No default password exists.

## Sign in once, operate until expiry

The following session and public-view protections apply when User login is enabled.

Choose **Operator sign in** in the browser. Pick **15 minutes**, **1 hour**
(default), or **8 hours**. Settings and manual transmit controls become
available until the chosen absolute expiry. Normal activity does not silently
extend the session. **Extend session** requires the password again.

**Lock now** revokes only that browser session immediately. Expiry returns the
browser to the public dashboard. Ordinary backend restarts also revoke sessions. A planned in-app update may carry over only the exact local browser session that initiated it, without extending its expiry; other viewers gain no access.
Scheduled beacons, digipeating, IGating and other configured background work
continue independently of browser authentication.

Each password or local launch login gets a random, host-only, HttpOnly, SameSite=Strict cookie and a
separate anti-CSRF token. The backend checks the session for every privileged
request. No global authenticated/unlocked flag exists. An operator signing in
on localhost or a VPN address never unlocks another visitor's browser, even
if both browsers share an IP or use the same reverse proxy. Localhost, VPN
addresses, and forwarding headers never bypass authentication.

Tabs in the **same browser profile at the same hostname** share its session,
as with ordinary website logins. A different browser/profile/device must sign
in independently. Cookies are scoped by hostname, so signing in at localhost
does not sign that browser in at a public hostname. Sessions are bearer
credentials: copying a profile/cookie can copy its access. Keep host and
browser profiles private; do not share an operator browser profile with viewers.

## Public hosting

- Publish through an HTTPS reverse proxy. Keep PropView's backend port private
  to the host/proxy, or to a trusted VPN when operating privately.
- Preserve the public Host and scheme. Configure trusted proxy addresses in
  your ASGI/server deployment rather than trusting arbitrary forwarding headers.
  The normal local reverse-proxy arrangement can forward HTTPS scheme to
  Uvicorn from loopback. Cookies use Secure when the app sees HTTPS.
- Forward cookies per client. Never inject a shared operator cookie or cache
  operator API responses. API responses use `Cache-Control: no-store` and
  `Vary: Cookie`.
- Forward `/ws` for live updates. Each outgoing message is checked against
  that socket's browser session, including after logout/expiry/reset.
- Do not expose the installation/data directory through a web server.

Public users can view stations, non-message packet data, propagation,
analytics, and weather; map pan/zoom, filters, theme, and radar controls remain
browser-local. Operator-only controls are hidden, and direct API calls are
rejected independently of the UI. Unknown/new API endpoints require operator
access unless explicitly added to the public read allowlist.

Public configuration contains display fields only. Configuration exports,
integration credentials, host connection details, message history/contacts,
and detailed diagnostics require login. Public WebSocket output excludes
messages, GPS jobs, and unknown event types. Custom base-map credentials stay
behind the tile proxy. Custom credential-bearing radar sources are disabled
for public viewers; built-in radar sources remain available.

## Upgrading existing installations

After installing this version, enable User login in Settings → Security before publishing
to change settings or transmit manually. The old mobile PIN and browser-local
"Protect transmit settings" preference do not grant operator permission.
The mobile PIN screen is replaced by operator sign-in. Existing radio and
scheduled services continue with their saved configuration.

For unattended dashboards use public viewer mode; it does not require login.
Automation that writes the HTTP API must obtain its own expiring login cookie
and send the returned `csrf_token` as `X-PropView-CSRF` with each write. Do not
reuse the operator's browser cookie in a public proxy.

## What's new after an update

The application bundles its release notes; no external service is needed to
load them. **What's new** shows the installed version and its changes the first
time an operator opens an updated installation. **Got it** (or Escape) records
dismissal for that version in `release-state.json`; routine browser refreshes,
new browser profiles, and application restarts do not show it again. Public
viewers cannot consume or dismiss the host's pending update notice. A fresh
installation uses the first-run setup guide instead of an update popup.

The owner-only `operator-desktop.json` launcher capability must remain private,
just like `operator-auth.json`. These files and the temporary `operator-update-session.json` handoff do not belong in a public web directory
or a container build context. In containers/headless deployments without a
browser, the local shortcut/tray convenience is unavailable; remote sessions
remain authenticated and public viewing remains read-only.

## Finding operator access

On the desktop dashboard, click the small lock icon in the map toolbar. Its popover shows public/local/remote operator status and remaining time, with Sign in or Extend session and Lock now. The mobile companion uses a compact floating lock button when the desktop toolbar is absent. Closing this popover does not end the session; Lock now does.
