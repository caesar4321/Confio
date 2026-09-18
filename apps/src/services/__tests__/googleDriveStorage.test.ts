import { googleDriveStorage, GoogleDriveStorageError } from '../googleDriveStorage';

describe('googleDriveStorage', () => {
    const originalFetch = globalThis.fetch;

    it('generates two IDs specifically for appDataFolder', async () => {
        globalThis.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ ids: ['drive-payload-id', 'drive-manifest-id'] }) });
        await expect(googleDriveStorage.generateRecoveryFileIds('token')).resolves.toEqual(['drive-payload-id', 'drive-manifest-id']);
        expect((globalThis.fetch as jest.Mock).mock.calls[0][0]).toContain('space=appDataFolder');
    });
    it('sends the reserved ID on create and preserves a conflict as a typed error', async () => {
        globalThis.fetch = jest.fn().mockResolvedValue({ ok: false, status: 409, text: async () => '{}' });
        await expect(googleDriveStorage.createFile('token', 'wallet', 'ciphertext', 'reserved-drive-id'))
            .rejects.toMatchObject({ status: 409, operation: 'upload' });
        expect((globalThis.fetch as jest.Mock).mock.calls[0][1].body).toContain('"id":"reserved-drive-id"');
    });
    it.each([[], ['one'], ['duplicate-id', 'duplicate-id'], ['invalid/id', 'valid-file-id']].map(ids => ({ ids })))('rejects invalid generated IDs $ids', async ({ ids }) => {
        globalThis.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ ids }) });
        await expect(googleDriveStorage.generateRecoveryFileIds('token')).rejects.toMatchObject({ reason: 'invalid_ids' });
    });

    it('reads past an empty partial page before declaring a backup missing', async () => {
        globalThis.fetch = jest.fn()
            .mockResolvedValueOnce({ ok: true, json: async () => ({ files: [], nextPageToken: 'next-page' }) })
            .mockResolvedValueOnce({ ok: true, json: async () => ({ files: [{ id: 'backup', name: 'wallet' }] }) });
        await expect(googleDriveStorage.listFiles('token', 'wallet')).resolves.toEqual([{ id: 'backup', name: 'wallet' }]);
        expect((globalThis.fetch as jest.Mock).mock.calls[1][0]).toContain('pageToken=next-page');
    });

    it.each([{ files: [], incompleteSearch: true }, { files: false }, { files: [{}] }])(
        'does not treat an incomplete or malformed listing as absence: %j', async body => {
            globalThis.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => body });
            await expect(googleDriveStorage.listFiles('token', 'wallet')).rejects.toMatchObject({
                name: 'GoogleDriveStorageError', operation: 'list',
            });
        },
    );

    it('rejects a repeated page token instead of looping indefinitely', async () => {
        globalThis.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ files: [], nextPageToken: 'same' }) });
        await expect(googleDriveStorage.listFiles('token')).rejects.toMatchObject({ name: 'GoogleDriveStorageError' });
    });

    it('does not treat a failed revision listing as an empty history', async () => {
        globalThis.fetch = jest.fn().mockResolvedValue({
            ok: false, status: 401, text: jest.fn().mockResolvedValue('{}'),
        });
        await expect(googleDriveStorage.listRevisions('token', 'file')).rejects.toMatchObject({
            name: 'GoogleDriveStorageError', status: 401, operation: 'revisions',
        });
    });

    it('types network failures without exposing transport diagnostics', async () => {
        globalThis.fetch = jest.fn().mockRejectedValue(new TypeError('private transport details'));
        await expect(googleDriveStorage.listFiles('token')).rejects.toMatchObject({
            name: 'GoogleDriveStorageError', status: 0, reason: 'network_error',
        });
    });

    afterEach(() => {
        jest.useRealTimers();
        globalThis.fetch = originalFetch;
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
        globalThis.fetch = jest.fn().mockResolvedValue({
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
        globalThis.fetch = jest.fn().mockResolvedValue({
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
        globalThis.fetch = jest.fn().mockResolvedValue({
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
        globalThis.fetch = jest.fn().mockResolvedValue({
            ok: true,
            json: jest.fn().mockResolvedValue({ files: [] }),
        } as any);

        await googleDriveStorage.listFiles('token');

        expect(globalThis.fetch).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ signal: expect.any(Object) }),
        );
    });

    it('turns an expired Drive request into a recoverable storage error', async () => {
        jest.useFakeTimers();
        globalThis.fetch = jest.fn((_url, init) => new Promise((_resolve, reject) => {
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
