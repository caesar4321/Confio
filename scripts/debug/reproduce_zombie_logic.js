
// Constants from .env.mainnet
const CONFIO_ASSET_ID = 3351104258;
const CUSD_ASSET_ID = 3198259450;
const USDC_ASSET_ID = 31566704;

// Luisg Data (from check_luisg.py)
const V2_DATA = {
    amount: 300000, // 0.3 ALGO
    assets: [
        { 'asset-id': 3198259450, amount: 0 }, // cUSD Opt-in
        { 'asset-id': 3351104258, amount: 0 }  // CONFIO Opt-in
    ]
};

const V1_DATA = {
    amount: 667000, // 0.667 ALGO (Approx)
    assets: [
        { 'asset-id': 3198259450, amount: 9260592 }, // ~9.2 cUSD
        { 'asset-id': 31566704, amount: 0 }
    ]
};

function checkLogic() {
    console.log("--- Starting Logic Verification for luisg ---");

    // 1. Check V2
    const v2Balance = V2_DATA.amount;
    const v2Assets = V2_DATA.assets;

    // EXACT CODE FROM migrationService.ts (Step 1021)
    const relevantV2Assets = v2Assets.filter((a) => {
        const aid = a['asset-id'];
        const amount = a['amount'];
        return ((aid === CONFIO_ASSET_ID || aid === CUSD_ASSET_ID || aid === USDC_ASSET_ID) && amount > 0);
    });
    // If V2 has < 1.0 ALGO and NO Asset Balance, it is likely just "Opted In" but not migrated.
    const isV2Empty = (v2Balance < 1000000 && relevantV2Assets.length === 0);

    console.log(`V2 Balance: ${v2Balance}`);
    console.log(`Relevant V2 Assets (Amount > 0): ${relevantV2Assets.length}`);
    console.log(`isV2Empty (Expected TRUE): ${isV2Empty}`);

    if (isV2Empty) {
        console.log("-> V2 is Empty. Checks V1...");

        // 2. Check V1
        const v1Balance = V1_DATA.amount;
        const v1Assets = V1_DATA.assets;

        // EXACT CODE FROM migrationService.ts
        const relevantV1Assets = v1Assets.filter((a) => {
            const aid = a['asset-id'];
            const amount = a['amount'];
            return ((aid === CONFIO_ASSET_ID || aid === CUSD_ASSET_ID || aid === USDC_ASSET_ID) && amount > 0);
        });

        const isZombie = (relevantV1Assets.length > 0 || v1Balance >= 300000);

        console.log(`V1 Balance: ${v1Balance}`);
        console.log(`Relevant V1 Assets (Amount > 0): ${relevantV1Assets.length}`);
        console.log(`isZombie Condition (Assets > 0 || V1 >= 0.3): ${isZombie}`);

        if (isZombie) {
            console.log("RESULT: ZOMBIE CONFIRMED ✅ (Migration Resumes)");
        } else {
            console.log("RESULT: FALSE ALARM ❌ (Migration Skipped)");
        }
    } else {
        console.log("RESULT: V2 Considered Funded ❌ (Success)");
    }
}

checkLogic();
