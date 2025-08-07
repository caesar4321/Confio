"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.ephemeralKeyStore = void 0;
// In-memory store for ephemeral key pairs
// In production, you'd want to use Redis or a database
const keyPairStore = new Map();
exports.ephemeralKeyStore = {
    store(id, keyPair) {
        keyPairStore.set(id, keyPair);
    },
    retrieve(id) {
        return keyPairStore.get(id);
    },
    delete(id) {
        keyPairStore.delete(id);
    },
    // Clean up old entries (call periodically)
    cleanup() {
        const now = Date.now() / 1000;
        for (const [id, keyPair] of keyPairStore.entries()) {
            if (keyPair.expiryDateSecs < now) {
                keyPairStore.delete(id);
            }
        }
    }
};
//# sourceMappingURL=ephemeralKeyStore.js.map