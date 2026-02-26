## Title
Add Confio ecosystem and repository

## Summary
This PR adds the **Confio** ecosystem and its primary public repository so it can be included in Electric Capital Open Dev Data.

## Migration file
Create a new file in `migrations/` named with the current UTC timestamp, for example:

`migrations/2026-02-26T153000_add_confio`

Use this content:

```lua
ecoadd Confio
ecocon Algorand Confio
repadd Confio https://github.com/caesar4321/Confio #wallet #payments #stablecoin
```

## Validation
Run locally before opening the PR:

```bash
uvx open-dev-data validate
```

(or if installed)

```bash
open-dev-data validate
```

## Context
- Project website: https://confio.lat
- Repository: https://github.com/caesar4321/Confio
- Confio is an open-source wallet/payment project built on Algorand.

## Notes
- If `Confio` already exists in taxonomy, this PR should be changed to only add missing `repadd` entries.
