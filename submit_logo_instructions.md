# How to Add CONFIO Logo to Algorand Wallets & Explorers

## Current Logo URL
The CONFIO logo is hosted at:
```
https://raw.githubusercontent.com/caesar4321/Confio/main/web/src/images/CONFIO.png
```

## Method 1: Pera Wallet Registry (Recommended)
Pera Wallet is the most popular Algorand wallet. Submit your asset here:

1. Go to: https://github.com/perawallet/pera-wallet-asset-meta
2. Fork the repository
3. Add a new file: `assets/743890784/metadata.json` with:
```json
{
  "asset_id": 743890784,
  "name": "Confío",
  "unit_name": "CONFIO",
  "logo": "https://raw.githubusercontent.com/caesar4321/Confio/main/web/src/images/CONFIO.png",
  "url": "https://confio.lat",
  "description": "Utility and governance coin for the Confío app",
  "total": 1000000000000000,
  "decimals": 6
}
```
4. Create a Pull Request
5. Once merged, logo will appear in Pera Wallet

## Method 2: Tinyman Registry
Tinyman is Algorand's main DEX:

1. Go to: https://github.com/tinymanorg/asa-list
2. Fork and add to `assets/testnet.json` (for testnet):
```json
{
  "id": 743890784,
  "name": "Confío",
  "unit_name": "CONFIO",
  "icon": "https://raw.githubusercontent.com/caesar4321/Confio/main/web/src/images/CONFIO.png"
}
```
3. Submit Pull Request

## Method 3: Algorand Foundation Registry (For Mainnet)
When you deploy to mainnet:
1. Visit: https://info.algorand.foundation/asa-verification
2. Complete verification process
3. Provide logo and project details

## Method 4: AlgoExplorer
AlgoExplorer pulls from multiple sources automatically. Once added to Pera or Tinyman, it usually appears there too.

## Quick Fix for Testing
For immediate testing, you can:
1. Use Pera Wallet's custom asset feature
2. Manually add the logo URL in wallet settings
3. Some wallets auto-fetch from the GitHub URL if properly formatted

## Logo Requirements
- **Format**: PNG or SVG
- **Size**: 256x256px or 512x512px recommended
- **Background**: Transparent preferred
- **File size**: Under 100KB

## Current Status
- Asset ID: 743890784 (Testnet)
- Logo URL: https://raw.githubusercontent.com/caesar4321/Confio/main/web/src/images/CONFIO.png
- Website: https://confio.lat

Once submitted to these registries, the CONFIO logo will automatically appear in:
- Pera Wallet
- Tinyman
- AlgoExplorer
- Other Algorand wallets and dApps