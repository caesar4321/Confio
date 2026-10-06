/**
 * "A member was blocked" for screens that list member content but stay
 * mounted (Descubrir is a tab). They compare the version when they regain
 * focus and re-read once, instead of everything in the app refetching.
 */
let blockVersion = 0;

export function notifyMemberBlocked() {
  blockVersion += 1;
}

export function memberBlockVersion(): number {
  return blockVersion;
}
