
import { Platform } from 'react-native';

const DRIVE_UPLOAD_URL = 'https://www.googleapis.com/upload/drive/v3/files';
const DRIVE_API_URL = 'https://www.googleapis.com/drive/v3/files';
const DRIVE_REQUEST_TIMEOUT_MS = 12_000;

const DRIVE_AUTH_ERROR_MESSAGE = 'Google Drive rechazó el permiso de Confío. Vuelve a intentarlo para renovar el acceso.';

const normalizeDriveReason = (reason: unknown): string | null => {
    if (typeof reason !== 'string') return null;
    const normalized = reason.trim();
    return /^[A-Za-z0-9_.-]{1,80}$/.test(normalized) ? normalized : null;
};

const parseDriveReason = (rawResponse?: string): string | null => {
    if (!rawResponse) return null;
    try {
        const payload = JSON.parse(rawResponse);
        return normalizeDriveReason(
            payload?.error?.errors?.[0]?.reason
            ?? payload?.error?.status
            ?? payload?.error?.reason,
        );
    } catch (_error) {
        return null;
    }
};

const driveErrorMessage = (status: number, reason: string | null, operation: string): string => {
    if (status === 401) {
        return 'La autorización de Google Drive venció. Vuelve a intentarlo para iniciar sesión nuevamente.';
    }
    if (status === 403) {
        if (reason === 'storageQuotaExceeded') {
            return 'La cuenta de Google seleccionada no tiene espacio disponible en Drive.';
        }
        if (reason === 'domainPolicy') {
            return 'La configuración de esta cuenta de Google no permite que Confío use Drive.';
        }
        if (reason === 'accessNotConfigured' || reason === 'dailyLimitExceeded' || reason === 'userRateLimitExceeded') {
            return 'Google Drive no está disponible temporalmente para Confío. Intenta nuevamente más tarde.';
        }
        return DRIVE_AUTH_ERROR_MESSAGE;
    }
    return `No pudimos completar la operación de Google Drive (${operation}). Intenta nuevamente.`;
};

export interface DriveFile {
    id: string;
    name: string;
    modifiedTime?: string;
}

export class GoogleDriveStorageError extends Error {
    status: number;
    operation: string;
    reason: string | null;
    supportCode: string;

    constructor(operation: string, status: number, reason?: string | null) {
        const safeReason = normalizeDriveReason(reason) || null;
        super(driveErrorMessage(status, safeReason, operation));
        this.name = 'GoogleDriveStorageError';
        this.status = status;
        this.operation = operation;
        this.reason = safeReason;
        this.supportCode = `DRIVE-${status}-${(safeReason || operation).replace(/[^A-Za-z0-9]/g, '_').toUpperCase()}`;
    }
}

async function createDriveError(operation: string, response: Response): Promise<GoogleDriveStorageError> {
    let rawResponse: string | undefined;
    try {
        rawResponse = await response.text();
    } catch (error) {
        rawResponse = undefined;
    }
    return new GoogleDriveStorageError(operation, response.status, parseDriveReason(rawResponse));
}

async function driveFetch(
    operation: string,
    url: string,
    init: RequestInit,
): Promise<Response> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), DRIVE_REQUEST_TIMEOUT_MS);
    try {
        return await fetch(url, { ...init, signal: controller.signal });
    } catch (error: any) {
        if (error?.name === 'AbortError') {
            throw new GoogleDriveStorageError(operation, 0, 'request_timeout');
        }
        throw error;
    } finally {
        clearTimeout(timeout);
    }
}

/**
 * Service to interact with Google Drive AppData folder via REST API.
 * 
 * We use REST API because standard Google Sign-In provides the access token,
 * avoiding the need for a separate heavy Drive SDK dependency.
 */
export const googleDriveStorage = {
    /**
     * List files in the AppData folder.
     * @param accessToken - Valid Google OAuth Access Token
     * @param filename - Optional filename to filter by
     * @param trashed - Optional boolean to search trashed files (default false)
     */
    async listFiles(accessToken: string, filename?: string, trashed: boolean = false): Promise<DriveFile[]> {
        try {
            // Build query - don't include 'spaces' here, it's a separate URL param
            let query = `trashed=${trashed}`;
            if (filename) {
                query += ` and name='${filename}'`;
            }

            const response = await driveFetch(
                'list',
                `${DRIVE_API_URL}?spaces=appDataFolder&q=${encodeURIComponent(query)}&fields=files(id,name,modifiedTime)`,
                {
                    method: 'GET',
                    headers: {
                        Authorization: `Bearer ${accessToken}`,
                    },
                }
            );

            if (!response.ok) {
                throw await createDriveError('list', response);
            }

            const data = await response.json();
            return data.files || [];
        } catch (error) {

            throw error;
        }
    },

    /**
     * Download file content.
     * @param accessToken - Valid Google OAuth Access Token
     * @param fileId - ID of the file to download
     * @param revisionId - Optional revision ID to download a specific version
     */
    async downloadFile(accessToken: string, fileId: string, revisionId?: string): Promise<string> {
        try {
            let url = `${DRIVE_API_URL}/${fileId}`;
            if (revisionId) {
                url += `/revisions/${revisionId}`;
            }
            url += '?alt=media';

            const response = await driveFetch('download', url, {
                method: 'GET',
                headers: {
                    Authorization: `Bearer ${accessToken}`,
                },
            });

            if (!response.ok) {
                throw await createDriveError('download', response);
            }

            // We expect the content to be the Base64 string of the secret
            return await response.text();
        } catch (error) {

            throw error;
        }
    },

    /**
     * List revisions of a file
     */
    async listRevisions(accessToken: string, fileId: string): Promise<any[]> {
        try {
            const response = await driveFetch(
                'revisions',
                `${DRIVE_API_URL}/${fileId}/revisions?fields=revisions(id,modifiedTime,keepForever,size)`,
                {
                    method: 'GET',
                    headers: {
                        Authorization: `Bearer ${accessToken}`,
                    }
                }
            );

            if (!response.ok) return [];

            const data = await response.json();
            return data.revisions || [];
        } catch (e) {

            return [];
        }
    },

    /**
     * Create a new file in AppData folder.
     * @param accessToken - Valid Google OAuth Access Token
     * @param filename - Name of the file
     * @param content - Content (utf-8 string, e.g. Base64 encoded secret)
     */
    async createFile(accessToken: string, filename: string, content: string): Promise<string> {
        try {
            const metadata = {
                name: filename,
                parents: ['appDataFolder'],
            };

            const boundary = '-------314159265358979323846';
            const delimiter = `\r\n--${boundary}\r\n`;
            const closeDelim = `\r\n--${boundary}--`;

            const body =
                delimiter +
                'Content-Type: application/json\r\n\r\n' +
                JSON.stringify(metadata) +
                delimiter +
                'Content-Type: text/plain\r\n\r\n' +
                content +
                closeDelim;

            const response = await driveFetch('upload', `${DRIVE_UPLOAD_URL}?uploadType=multipart`, {
                method: 'POST',
                headers: {
                    Authorization: `Bearer ${accessToken}`,
                    'Content-Type': `multipart/related; boundary=${boundary}`,
                },
                body: body,
            });

            if (!response.ok) {
                throw await createDriveError('upload', response);
            }

            const data = await response.json();
            return data.id;
        } catch (error) {

            throw error;
        }
    },

    /**
     * Update an existing file's content.
     * @param accessToken - Valid Google OAuth Access Token
     * @param fileId - ID of the file to update
     * @param content - New content
     */
    async updateFile(accessToken: string, fileId: string, content: string): Promise<void> {
        try {
            const response = await driveFetch('update', `${DRIVE_UPLOAD_URL}/${fileId}?uploadType=media`, {
                method: 'PATCH',
                headers: {
                    Authorization: `Bearer ${accessToken}`,
                    'Content-Type': 'text/plain',
                },
                body: content,
            });

            if (!response.ok) {
                throw await createDriveError('update', response);
            }
        } catch (error) {

            throw error;
        }
    }
};
