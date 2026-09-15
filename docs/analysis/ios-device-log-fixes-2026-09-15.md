# iPhone device log investigation — 2026-09-15

Status: DONE_WITH_CONCERNS — fixes built and installed; fresh startup verified. The Bre-B location flow needs a device retry after local API restarts.

## Confirmed causes and fixes

- Local testnet PostgreSQL schema lagged behind the running code. Applied inbox 0011, conversion 0008–0013, and billing 0001–0014 using the existing migrations. Queries against `inbox_contentitem.push_claimed_at`, `billing_obligationsubject`, and `conversions.gross_amount_exact` now succeed.
- Firebase services used deprecated namespaced entry points and methods. Migrated authentication, messaging, analytics, Crashlytics, and App Check to the installed SDK's modular API.
- iOS registered an independent debug App Check factory before Firebase initialization, while JavaScript configured a different RNFirebase provider as App Attest. Registering `RNFBAppCheckModule.sharedInstance()` before `FirebaseApp.configure()` allows the JS configuration to control the actual provider. Removed the hardcoded native debug token and provisioning-profile heuristic. Existing explicit JS debug configuration remains the authority.
- Push registration redundantly registered already-registered iOS devices. Now checks registration state before registering.
- Different queries replaced subsets of the id-less `cusdPlusConvertParams` cache object. Added a merge policy and regression test preserving previously fetched fields.
- Screens 4.13.1 passes `box-none` to a UIKit header configuration view that implements its own hit testing. The persistent dependency patch omits that property on iOS and preserves it on other platforms.
- Screens logged every frame/bounds change via NSLog. The persistent patch moves those diagnostic messages to trace level.
- React Native 0.79.3 stored an NSNull trackingName in NSURLProtocol properties, causing iOS HTTP-cache serialization warnings. The persistent patch converts JSON null to nil before storing the optional string.

## Evidence

- Final Debug build for the connected iPhone: BUILD SUCCEEDED; installed and launched via devicectl.
- Full app suite: 71 suites / 637 tests passed. Used explicit Jest config and `--watchman=false`. The existing suite leaves open handles; the full run used `--forceExit` after tests completed.
- Final focused App Check run: 6 tests passed.
- TypeScript compiler comparison with the eight migrated service/app files read from HEAD: 376 existing diagnostics before and after, zero new diagnostics.
- Final 30-second JavaScript capture: 109 console events; 0 warnings, 0 errors, 0 uncaught exceptions.
- Final native capture: no pointerEvents errors, App Check token failures, invalid protocol-property-list warnings, or ScreenView layout spam. An RNFirebase initial debug-provider diagnostic remains before JavaScript configures App Attest.
- Dependency patches verified against installed files with reverse application checks; source diff whitespace check passed.

## Remaining limits

During location-screen investigation, the local API process changed and port 8000 temporarily refused connections. This was observed directly with process/listener checks and HTTP probes. Once startup completed, HTTP probes returned 200. This explains the observed connection refusals but does not establish that the complete location-attestation flow succeeds. Retry that flow on the device with the API stable.

Xcode/system messages about UIScene adoption, debugger-disabled Crashlytics, optional AdSupport, and vendor debug symbols are separate from the fixed application failures. Full UIScene migration and dependency upgrades were not performed. Final startup was captured through devicectl and the React Native inspector, not under Xcode's debugger, so absence of debugger-only messages is not evidence that those messages were fixed.

## Reusable debugging notes

Use devicectl for native stdout/stderr and Metro's `/json/list` inspector target with `Runtime.enable` for JavaScript logs; the native console alone does not include all JavaScript diagnostics. Do not store or publish raw logs without removing credentials and personal data.

Provider setup follows the [React Native Firebase App Check instructions](https://rnfirebase.io/app-check/usage), with API signatures checked against the installed 22.2.0 code. Modular migration follows the [v22 migration guide](https://rnfirebase.io/migrating-to-v22).
