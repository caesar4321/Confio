import { googleDriveStorage, GoogleDriveStorageError } from '../googleDriveStorage';

describe('googleDriveStorage', () => {
    const originalFetch = global.fetch;

    afterEach(() => {
        jest.useRealTimers();
        global.fetch = originalFetch;
        jest.restoreAllMocks();
    });

    it('keeps only a safe reason and support code from Google auth errors', async () => {
        const rawResponse = JSON.stringify({
            error: {
                code: 401,
                message: 'Request had invalid authentication credentials.',
                status: 'UNAUTHENTICATED',
                errors: [{ reason: 'authError' }],
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
            message: 'La autorización de Google Drive venció. Vuelve a intentarlo para iniciar sesión nuevamente.',
            reason: 'authError',
            supportCode: 'DRIVE-401-AUTHERROR',
        } satisfies Partial<GoogleDriveStorageError>);
    });

    it('shows an accurate message when Google reports exhausted storage', async () => {
        global.fetch = jest.fn().mockResolvedValue({
            ok: false,
            status: 403,
            text: jest.fn().mockResolvedValue(JSON.stringify({
                error: { errors: [{ reason: 'storageQuotaExceeded' }] },
            })),
        } as any);

        await expect(googleDriveStorage.createFile('token', 'wallet.enc', 'ciphertext'))
            .rejects.toMatchObject({
                status: 403,
                reason: 'storageQuotaExceeded',
                supportCode: 'DRIVE-403-STORAGEQUOTAEXCEEDED',
                message: 'La cuenta de Google seleccionada no tiene espacio disponible en Drive.',
            });
    });

    it('does not retain malformed or sensitive Google error bodies', async () => {
        global.fetch = jest.fn().mockResolvedValue({
            ok: false,
            status: 403,
            text: jest.fn().mockResolvedValue('{"error":{"reason":"user@example.com has no access"}}'),
        } as any);

        const error = await googleDriveStorage.listFiles('token').catch(value => value);
        expect(error).toMatchObject({
            reason: null,
            supportCode: 'DRIVE-403-LIST',
        });
        expect(error).not.toHaveProperty('rawResponse');
    });

    it('attaches an abort signal so Drive cannot hang sign-in indefinitely', async () => {
        global.fetch = jest.fn().mockResolvedValue({
            ok: true,
            json: jest.fn().mockResolvedValue({ files: [] }),
        } as any);

        await googleDriveStorage.listFiles('token');

        expect(global.fetch).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ signal: expect.any(Object) }),
        );
    });

    it('turns an expired Drive request into a recoverable storage error', async () => {
        jest.useFakeTimers();
        global.fetch = jest.fn((_url, init) => new Promise((_resolve, reject) => {
            init?.signal?.addEventListener('abort', () => {
                reject(Object.assign(new Error('aborted'), { name: 'AbortError' }));
            });
        })) as jest.Mock;

        const request = googleDriveStorage.listFiles('token');
        const assertion = expect(request).rejects.toMatchObject({
            name: 'GoogleDriveStorageError',
            status: 0,
            operation: 'list',
            reason: 'request_timeout',
            supportCode: 'DRIVE-0-REQUEST_TIMEOUT',
        } satisfies Partial<GoogleDriveStorageError>);
        await jest.advanceTimersByTimeAsync(12_000);

        await assertion;
    });
});
