# Registration restrictions

`security.RegistrationRestriction` denies creation of new Confío accounts from
an exact IP (`kind=ip`, canonical IPv4/IPv6) or recorded device fingerprint
(`kind=device`, SHA-256 produced by `calculate_device_fingerprint`). Set
`is_active=False` to lift a restriction. Record the investigation and review
reason in `reason`; do not commit personal identifiers to this document.

The Web3Auth login mutation checks these rows after Firebase verification but
before creating a user, tracking devices, or issuing tokens. An existing active,
unbanned account remains able to log in from a restricted registration source.
Inactive/deleted accounts and accounts with active UserBan records cannot log in.
This is distinct from IPAddress.is_blocked, which denies all requests.

Apply `security.0009_registrationrestriction` before restarting the app with
this change. Creating/deactivating rows takes effect without a restart or cache
invalidation. Existing UserBan middleware has a separate five-minute cache.

Limitations: device identifiers are supplied by the client; a modified client
can omit or change them. Legacy login without device information is retained.
IP changes also evade exact-IP restrictions. These controls reduce reuse of
known sources but do not prove physical device identity or prevent every
re-registration. Existing provider QR orders and on-chain assets are unaffected.

Verification: `python manage.py test security.test_login_restrictions`.
