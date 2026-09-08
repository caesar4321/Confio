# App Check login policy

Google and Apple login attempt App Check token acquisition but submit login even
when it returns no token. The backend still validates the Firebase identity token
and account restrictions first. No payment/withdrawal enforcement was relaxed.

`APP_CHECK_LOGIN_ENFORCE=True` is the default. Missing or invalid attestation
rejects login/signup. Setting it to `False` admits those requests past the
attestation check, records their failed verdict, and leaves all other login checks
in place. This is an operator-controlled login policy, never a client parameter.
Policy/diagnostic storage failures still fail closed.

## Deployment

1. Apply security migration `0010_integrityverdict_nullable_user` before running
   the new backend. This permits recording rejected pre-signup attempts without
   creating accounts or triggering account-creation signals.
2. Deploy the backend with `APP_CHECK_LOGIN_ENFORCE=True` and validate diagnostics.
3. Release the Android/iOS client changes. Old clients still block locally;
   changing the server setting cannot unblock those versions.
4. Any temporary warning-mode change requires an explicit operator decision and
   application-worker configuration reload/restart. Restore `True` to re-enable
   strict login enforcement. No Firebase console settings change automatically.

Keep the nullable-column migration when rolling back application code; anonymous
verdicts may already exist. Older admin code must not assume every verdict has a
user. Do not reverse the migration with anonymous records still present.

## Diagnostics

`IntegrityVerdict.raw_response.login_diagnostics` contains fixed client error
categories, numeric build number, and `android`/`ios` platform. Headers are
untrusted hints; unknown values are replaced with `unknown`. Old clients' native
messages are classified server-side and discarded, never copied into login logs.
New clients send only categories. No token prefix, native error dump, email, or
device model is added to these diagnostics.

An anonymous signup verdict has `user=null`. Admitted signup verdicts are linked
after account creation. A failed attestation is not proof of rooting, fraud, or
malware. A passed attestation is not proof that every subsequent login step
succeeded. Aggregate build/platform/category counts and compare subsequent login
success; do not treat client build headers as trusted security evidence.

The change reuses the existing login endpoint, identity validation, and access
restrictions. It creates no unauthenticated telemetry endpoint. Diagnose only
requests that reach the backend: network failures and old client-side blocks
remain outside this dataset.
