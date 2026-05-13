import { googleDriveStorage, GoogleDriveStorageError } from '../googleDriveStorage';

describe('googleDriveStorage', () => {
    const originalFetch = global.fetch;

    afterEach(() => {
        global.fetch = originalFetch;
        jest.restoreAllMocks();
    });

    it('does not expose raw Google auth errors to UI callers', async () => {
        const rawResponse = JSON.stringify({
            error: {
                code: 401,
                message: 'Request had invalid authentication credentials.',
                status: 'UNAUTHENTICATED',
            },
        });
        global.fetch = jest.fn().mockResolvedValue({
            ok: false,
            status: 401,
            text: jest.fn().mockResolvedValue(rawResponse),
        } as any);

        await expect(googleDriveStorage.listFiles('bad-token')).rejects.toMatchObject({
            name: 'GoogleDriveStorageError',
            status: 401,
            operation: 'list',
            message: 'No pudimos acceder a Google Drive. Vuelve a tocar Reintentar respaldo y elige la cuenta de Google correcta.',
            rawResponse,
        } satisfies Partial<GoogleDriveStorageError>);
    });
});
