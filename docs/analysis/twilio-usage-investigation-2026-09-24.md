# Twilio usage and abuse investigation — 2026-09-24

Status: DONE_WITH_CONCERNS. Read-only investigation of Twilio and production; no configuration, application code, or users changed.

## Finding

No strong evidence of broad SMS pumping in the available records. The recent increase is concentrated in Bolivia and is more consistent with new-user growth. This does not prove every signup is legitimate. Real production control gaps remain.

## Billing

Twilio Usage Records show $96.9484 for September 1–24 UTC, versus $51.5950 for August 1–24 (+87.9%). September 24 is partial. All of August cost $75.3264.

Non-overlapping September components reconcile exactly:
- SMS delivery: $77.7664 (398 billed messages).
- Successful verification fees: $15.1500 (303).
- Paid line-type lookups: $4.0320 (504).

Do not sum Twilio's parent/child category aliases: `sms`, `channels`, `authy-sms-outbound`, and `sms-outbound` overlap.

September 1–22 averaged $3.3684/day. September 23 cost $8.5842; September 24 was already $14.2589 (4.23× the earlier daily average).

## Destination-country breakdown

September 1 through the fetched September 24 snapshot. The latest attempt in the response was 16:47:47 UTC. Country is Twilio's destination country, not user residence. “Completed” means the attempt's conversion status is converted; it is not a unique-user count. Delivery costs exclude successful-verification and lookup fees.

| Country | Attempts | Unique phones | Completed | Completion | Delivery USD |
|---|---:|---:|---:|---:|---:|
| Venezuela | 139 | 115 | 110 | 79.1% | $31.3723 |
| Bolivia | 109 | 92 | 72 | 66.1% | $24.1435 |
| Peru | 49 | 45 | 43 | 87.8% | $12.1324 |
| Mexico | 20 | 17 | 16 | 80.0% | $3.6380 |
| Argentina | 22 | 14 | 15 | 68.2% | $2.2649 |
| Brazil | 22 | 14 | 15 | 68.2% | $1.3178 |
| Colombia | 22 | 19 | 19 | 86.4% | $1.3024 |
| Chile | 7 | 5 | 3 | 42.9% | $0.5524 |
| Guatemala | 2 | 2 | 2 | 100.0% | $0.4996 |
| Italy | 4 | 2 | 2 | 50.0% | $0.3708 |
| El Salvador | 1 | 1 | 1 | 100.0% | $0.2990 |
| Japan | 2 | 2 | 2 | 100.0% | $0.1780 |
| Spain | 1 | 1 | 1 | 100.0% | $0.0875 |
| United States | 2 | 2 | 2 | 100.0% | $0.0256 |

Total: 402 attempts, 331 distinct phones, 303 converted attempts (75.37%), $78.1842 in attempt-level delivery prices. Venezuela, Bolivia, and Peru account for 86.52% of that delivery cost. Observed per-attempt costs are approximately $0.2257, $0.2215, and $0.2476 respectively.

The attempt total differs from Usage Records by four messages and $0.4178. This is an unresolved cross-source reconciliation difference; do not add attempt prices to billed SMS charges. Twilio documents that attempt prices can change and may take 24 hours to finalize. The 30-day response also includes RCS (`rbm`) attempts, so “attempts” is broader than SMS transport. There were 474 distinct attempt SIDs, one service, USD throughout, and no missing attempt prices. Twilio's independent Attempts Summary agrees exactly with September's 402 attempts / 303 converted / 99 unconverted.

## The Bolivia spike

- September 1–22: 38 attempts, 27 distinct phones, 21 converted.
- September 23: 28 attempts; September 24: 43 attempts.
- Combined September 23–24: 71 attempts to 65 distinct phones, 51 converted (71.8%), $15.7265 delivery cost.
- Carrier distribution: Entel 35, Tigo 23, Viva 13. No single-carrier concentration.
- Production's retained SMS records for Bolivian numbers since September 23: 63 records, 59 users, 63 phone numbers, 51 marked verified. 58 of the 59 users joined since September 23.
- These users have 59 distinct recorded integrity devices, with no device shared across these users, and 61 distinct associated IPs. The largest IP association contains two users. No suspicious association flags were set in this cohort.
- All-country signups also increased: 47 on September 23 and 62 on September 24, versus 418 / 22 = 19.0 per day on September 1–22.

This supports a growth explanation more than a bulk-message attack. Device fingerprints and proxy-derived IPs are signals, not proof of independent humans. IP-country fields were empty, so IP geography was not established. Shared IP/device results describe retained associations, not a complete per-request network history.

## Security and reliability findings

1. **Paid lookup occurs before all SMS rate limits.** `sms_verification/schema.py:157` invokes line-type lookup; limits begin at line 167. The deployed revision `6fbd09bbc` has the same ordering. An authenticated caller can incur paid lookups even when the later SMS limiter rejects the request. Current lookup spend is only 4.16% of the bill, so this is an exposure rather than the demonstrated cause of this increase.
2. **App Check enforcement is disabled in production.** The loaded Django setting is `APP_CHECK_ENFORCE=False`. Six missing-token requests were logged since September 22. Redis is enabled, so limits are shared rather than process-local.
3. **No custom Twilio Verify service rate limits are configured.** The service's RateLimits API returned an empty list. Twilio's built-in limits may still apply. Fraud Guard and geographic-permission configuration were not established by this inspection; do not infer they are disabled.
4. **Retries delete active local verification records before checking limits.** Line 165 removes an unverified record before the cooldown check. A rejected resend can invalidate the local record needed to check the already-delivered code. This is a concrete ordering problem; its share of failed conversions has not been measured.
5. **Cooldown and first-counter initialization are not fully atomic.** The code uses separate get/set operations and incr-then-set on missing keys. Concurrent requests may bypass intended thresholds; no attack reproduction was performed against production.

Since September 22, production logs contain 119 “Twilio Verify started” events, matching the 119 Twilio attempts in that date range, and four rate-limit warning events. This is a count-level cross-check, not a SID-level attribution proof. The full 30-day maximum for one destination was six messages, five converted; there was no large repeated-destination flood in these records.

## Recommended next actions

1. Put cheap, atomic user/IP/device limits before any paid lookup; cache carrier results and make cooldown admission atomic.
2. Preserve the active verification until a replacement send succeeds. Add mocked regression tests for rejected resends and lookup calls blocked by limits.
3. Restore App Check enforcement after checking client compatibility and the reason for its September 9 kill-switch change.
4. Review Verify Fraud Guard and destination permissions in Twilio Console; add country-volume/spend alerts and explicit custom rate limits if appropriate. Country blocking is not supported by this evidence for the main three destinations.

## Sources and method

Fetched live on September 24, 2026, approximately 17:20–17:29 UTC:
- Twilio Usage Records: GET `/2010-04-01/Accounts/{AccountSid}/Usage/Records/ThisMonth.json`, `/LastMonth.json`, and `/Daily.json?StartDate=2026-08-01&EndDate=2026-09-24&Category=totalprice`.
- Twilio Verify: GET `/v2/Attempts?PageSize=1000` (one page, all 474 records), `/v2/Attempts/Summary?DateCreatedAfter=2026-09-01T00:00:00Z`, `/v2/Services`, and the configured service's `/RateLimits`.
- Country aggregation: filter `date_created >= 2026-09-01`, group by `channel_data.country`, count distinct `channel_data.to`, sum Decimal `price.value`, count `conversion_status == converted`.
- Production Django queries ran inside a READ ONLY transaction with a 20-second statement timeout. Sources: SMSVerification, User.all_objects, IntegrityVerdict, IPDeviceUser. SMS rows filter created_at >= September 1; recent Bolivia adds phone prefix +591 and created_at >= September 23. Integrity rows filter cohort user IDs and created_at >= September 1; IP associations filter cohort user IDs and last_seen >= September 23. Signup counts use date_joined >= September 1.
- Production service logs since September 22, and local/deployed verification implementation.

The app deletes older unverified records, so its SMS table is not a complete send ledger. The provider's Attempts API only covers the last 30 days; full-August country detail was not available from it. Latest-day conversions and prices are provisional. This investigation does not rule out sophisticated signup fraud or unrelated credential misuse.

References: [Twilio Attempts API](https://www.twilio.com/docs/verify/api/attempts), [Usage Records](https://www.twilio.com/docs/usage/api/usage-record).
