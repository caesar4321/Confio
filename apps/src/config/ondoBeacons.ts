// The beacons Ondo's GM stock tokens on BSC point at (EIP-1967 beacon
// proxies): read from the chain for every bundled token on 2026-10-26
// (450 on the first, 7 on the second). The Emergency Exit admits a token it
// only remembered (listed after this build) when its proxy code and beacon
// are these, so the code it calls is Ondo's. Re-check before a release:
// npm run check:ondo-beacons (needs network).
export const ONDO_GM_BEACONS: readonly string[] = [
  '0xc046b05a920e4b412815934dd8e58904dda73315',
  '0x16ba2c6cdcdca14a6e071255a7cf28318ba193d8',
];

// keccak256 of their proxies' runtime code (824 bytes on the first beacon,
// 305 on the second, whose code embeds its beacon). The slot alone is only
// storage any contract can write: the code is what proves the proxy really
// delegates to Ondo's beacon.
export const ONDO_GM_PROXY_CODE_HASHES: readonly string[] = [
  '0x439923c85f956f038ae77871736f789e6d08d22257b6e5fdccfdc83924ecb4d0',
  '0x68981643df1a58b626359ac7176170ab8a09b409db2d5e7e1f8fe0ca161317fa',
];
