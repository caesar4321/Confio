# Referral Reward Identity Policy

This document describes the current referral reward control model tied to personal Didit KYC.

## Goal

Referral compensation must be limited to one real person per referee bonus, even if the same person creates multiple accounts.

## Identity Key

- Duplicate-person detection uses the tuple `(document_issuing_country, document_number_normalized)`.
- `document_number_normalized` is only the cleaned document number.
- Country is stored separately and is always part of the duplicate check.
- Example:
  - `(VEN, V26108685)` and `(COL, V26108685)` are different identities for this policy.
  - `(VEN, V26108685)` and `(VEN, V26108685)` are treated as the same real-person identity candidate.

## Current Rules

### Referee side

- A user account can only register one referrer via `UserReferral(referred_user=...)`.
- A referee cannot claim referral-earned `$CONFIO` unless that same account has completed personal Didit verification.
- A referee also cannot withdraw reward-funded `$CONFIO` unless that same account is personally verified.
- If several referred accounts resolve to the same verified personal identity:
  - only the earliest referral tied to that identity keeps the reward
  - later duplicate referrals are failed on the referee side

### Referrer side

- A referrer cannot claim just because the referred user already deposited or activated the reward.
- The referred user must first complete personal Didit verification.
- If the referred user is still unverified, the referrer sees:
  - `Tu referido ya activó este bono, pero debe completar su verificación de identidad en Didit para liberar esta recompensa.`
- If the referred user started KYC and is still pending, the referrer sees:
  - `Tu referido ya activó este bono, pero todavía debe terminar su verificación de identidad en Didit para que puedas reclamar la recompensa.`
- If the referred user later resolves to a duplicate verified identity, the losing referral is also failed on the referrer side.

### Verified rewarded withdrawals

- Reward or referral-funded `$CONFIO` requires verified personal KYC.
- Once the user is verified and the reward is validly earned, rewarded `$CONFIO` is not escalated to manual review purely because the withdrawal is large.

## Duplicate Identity Policy

### KYC status

- Duplicate personal identities are still allowed to become `verified`.
- We do not defer duplicate personal KYC to `pending` only because of duplication.
- Duplicate identity evidence is still recorded in `risk_factors.duplicate_identity` and `SuspiciousActivity`.

### Reward effect

- Duplicate verified identities do not get duplicate referral compensation.
- The earliest referral for that verified identity wins.
- Later referrals tied to the same verified identity are failed for both:
  - `referee_reward_status`
  - `referrer_reward_status`
- Related `ReferralRewardEvent` rows are also failed unless they were already claimed earlier.

## Enforcement Points

The policy is enforced in these places:

1. `security/models.py`
   - when a verified personal identity is saved and duplicates are detected
2. `achievements/services/referral_rewards.py`
   - when referral reward eligibility is created from a qualifying event
3. `users/schema.py`
   - when referee or referrer claims are prepared and submitted
4. `blockchain/mutations.py`
   - when reward-funded `$CONFIO` withdrawals are attempted

This layered enforcement is intentional so stale eligibility or cached claim sessions cannot bypass the policy.

## Admin Visibility

- `IdentityVerification` admin exposes:
  - `document_number`
  - `document_issuing_country`
  - `document_number_normalized`
  - `risk_factors`
- The admin dashboard reward widgets distinguish:
  - reward `$CONFIO` available to verified users
  - reward `$CONFIO` on KYC hold
  - rewarded users split by verified vs unverified
  - duplicate identities detected

## Important Limitation

This policy blocks future and unclaimed duplicate rewards.

It does **not** claw back rewards that were already fully claimed before duplicate identity evidence was known and before these controls were deployed.

## Key Files

- `security/models.py`
- `security/admin.py`
- `achievements/referral_security.py`
- `achievements/services/referral_rewards.py`
- `users/schema.py`
- `blockchain/mutations.py`
- `security/tests.py`
- `achievements/tests/test_referral_rewards.py`
