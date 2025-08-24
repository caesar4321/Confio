import { apolloClient } from '../apollo/client'
import { gql } from '@apollo/client'
import { REQUEST_DISPUTE_EVIDENCE_UPLOAD, ATTACH_DISPUTE_EVIDENCE } from '../apollo/mutations'
import { uploadFileToPresigned, uploadFileToPresignedForm } from './uploadService'

export type PresignedUpload = {
  url: string
  key: string
  method: string
  headers: Record<string, string>
  expiresIn: number
}

export class DisputeEvidenceService {
  async requestUpload(tradeId: string, opts: { filename?: string; contentType?: string; sha256?: string } = {}): Promise<{
    success: boolean
    error?: string
    upload?: PresignedUpload
  }> {
    const { data } = await apolloClient.mutate({
      mutation: REQUEST_DISPUTE_EVIDENCE_UPLOAD,
      variables: {
        tradeId,
        filename: opts.filename,
        contentType: opts.contentType || 'video/mp4',
        sha256: opts.sha256,
      },
      fetchPolicy: 'no-cache',
    })
    const res = data?.requestDisputeEvidenceUpload
    return { success: !!res?.success, error: res?.error || undefined, upload: res?.upload || undefined }
  }

  async attach(tradeId: string, key: string, meta?: { size?: number; sha256?: string; etag?: string }): Promise<{ success: boolean; error?: string }> {
    const { data } = await apolloClient.mutate({
      mutation: ATTACH_DISPUTE_EVIDENCE,
      variables: { tradeId, key, size: meta?.size, sha256: meta?.sha256, etag: meta?.etag },
      fetchPolicy: 'no-cache',
    })
    const res = data?.attachDisputeEvidence
    return { success: !!res?.success, error: res?.error || undefined }
  }

  async uploadEvidence(
    tradeId: string,
    localUri: string,
    opts: { filename?: string; contentType?: string; sha256?: string; size?: number } = {}
  ): Promise<{ success: boolean; error?: string }> {
    // 1) Request presigned URL
    const req = await this.requestUpload(tradeId, { filename: opts.filename, contentType: opts.contentType, sha256: opts.sha256 })
    if (!req.success || !req.upload) return { success: false, error: req.error || 'Failed to get upload URL' }

    const up = req.upload
    // 2) Upload to S3 (POST with fields preferred; fallback to PUT)
    if (String(up.method).toUpperCase() === 'POST' && (up as any).fields) {
      const fieldsRaw = (up as any).fields
      const fieldsObj = typeof fieldsRaw === 'string' ? JSON.parse(fieldsRaw) : (fieldsRaw || {})
      await uploadFileToPresignedForm(up.url, fieldsObj, localUri, opts.filename || 'evidence.mp4', opts.contentType || 'video/mp4')
    } else if (String(up.method).toUpperCase() === 'PUT') {
      await uploadFileToPresigned(up.url, up.headers || { 'Content-Type': opts.contentType || 'video/mp4' }, localUri)
    } else {
      return { success: false, error: 'Unsupported upload method' }
    }

    // 3) Attach evidence key to dispute
    const att = await this.attach(tradeId, up.key, { size: opts.size, sha256: opts.sha256 })
    if (!att.success) return { success: false, error: att.error || 'Failed to attach evidence' }

    return { success: true }
  }
}

export const disputeEvidenceService = new DisputeEvidenceService()
