import { googleDriveStorage, GoogleDriveStorageError } from '../googleDriveStorage';

describe('googleDriveStorage', () => {
    const originalFetch = global.fetch;

    afterEach(() => {
        jest.useRealTimers();
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
            rawResponse: 'request_timeout',
        } satisfies Partial<GoogleDriveStorageError>);
        await jest.advanceTimersByTimeAsync(12_000);

        await assertion;
    });
});
