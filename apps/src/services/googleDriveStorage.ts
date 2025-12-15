
import { Platform } from 'react-native';

const DRIVE_UPLOAD_URL = 'https://www.googleapis.com/upload/drive/v3/files';
const DRIVE_API_URL = 'https://www.googleapis.com/drive/v3/files';

export interface DriveFile {
    id: string;
    name: string;
    modifiedTime?: string;
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

            const response = await fetch(
                `${DRIVE_API_URL}?spaces=appDataFolder&q=${encodeURIComponent(query)}&fields=files(id,name,modifiedTime)`,
                {
                    method: 'GET',
                    headers: {
                        Authorization: `Bearer ${accessToken}`,
                    },
                }
            );

            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(`Drive List Failed: ${response.status} ${errorText}`);
            }

            const data = await response.json();
            return data.files || [];
        } catch (error) {
            console.warn('[GoogleDrive] List files failed:', error);
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

            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    Authorization: `Bearer ${accessToken}`,
                },
            });

            if (!response.ok) {
                throw new Error(`Drive Download Failed: ${response.status}`);
            }

            // We expect the content to be the Base64 string of the secret
            return await response.text();
        } catch (error) {
            console.warn('[GoogleDrive] Download failed:', error);
            throw error;
        }
    },

    /**
     * List revisions of a file
     */
    async listRevisions(accessToken: string, fileId: string): Promise<any[]> {
        try {
            const response = await fetch(
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
            console.warn('[GoogleDrive] Failed to list revisions', e);
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

            const response = await fetch(`${DRIVE_UPLOAD_URL}?uploadType=multipart`, {
                method: 'POST',
                headers: {
                    Authorization: `Bearer ${accessToken}`,
                    'Content-Type': `multipart/related; boundary=${boundary}`,
                },
                body: body,
            });

            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(`Drive Upload Failed: ${response.status} ${errorText}`);
            }

            const data = await response.json();
            return data.id;
        } catch (error) {
            console.warn('[GoogleDrive] Create file failed:', error);
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
            const response = await fetch(`${DRIVE_UPLOAD_URL}/${fileId}?uploadType=media`, {
                method: 'PATCH',
                headers: {
                    Authorization: `Bearer ${accessToken}`,
                    'Content-Type': 'text/plain',
                },
                body: content,
            });

            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(`Drive Update Failed: ${response.status} ${errorText}`);
            }
        } catch (error) {
            console.warn('[GoogleDrive] Update file failed:', error);
            throw error;
        }
    }
};
