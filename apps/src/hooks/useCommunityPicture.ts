import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery } from '@apollo/client';

import {
  REQUEST_COVER_PICTURE_UPLOAD,
  REQUEST_PROFILE_PICTURE_UPLOAD,
  SUBMIT_COVER_PICTURE,
  SUBMIT_PROFILE_PICTURE,
} from '../apollo/mutations';
import { GET_MY_COVER_PICTURE, GET_MY_PROFILE_PICTURE } from '../apollo/queries';
import { pickFromLibrary } from '../services/systemPicker';
import { uploadFileToPresignedForm } from '../services/uploadService';
import { usePollWhile } from './usePollWhile';
import { isSchemaMismatch } from '../utils/graphqlSchemaMismatch';

export type PictureKind = 'avatar' | 'cover';

type MyPicture = {
  url?: string | null;
  latestStatus?: 'PENDING' | 'ACTIVE' | 'REJECTED' | 'FAILED' | 'REMOVED' | null;
  latestReason?: string | null;
  blockMessage?: string | null;
  rulesRequired?: boolean | null;
};

const POLL_MS = 3000;
const POLL_GIVE_UP_MS = 120000;

const DOCS = {
  avatar: {
    query: GET_MY_PROFILE_PICTURE,
    request: REQUEST_PROFILE_PICTURE_UPLOAD,
    submit: SUBMIT_PROFILE_PICTURE,
    requestField: 'requestProfilePictureUpload',
    submitField: 'submitProfilePicture',
    pick: { maxWidth: 1024, maxHeight: 1024 },
  },
  cover: {
    query: GET_MY_COVER_PICTURE,
    request: REQUEST_COVER_PICTURE_UPLOAD,
    submit: SUBMIT_COVER_PICTURE,
    requestField: 'requestProfilePictureUpload',
    submitField: 'submitProfilePicture',
    pick: { maxWidth: 2048, maxHeight: 2048 },
  },
} as const;

/**
 * Pick, upload and track the member's own avatar or cover from wherever it
 * is shown. Every image is AI-reviewed before anyone else sees it; the
 * current one stays up meanwhile. `available` is false on a server without
 * this kind (an older server rejects the cover argument).
 */
export function useCommunityPicture(kind: PictureKind, enabled: boolean, refreshKey = 0) {
  const docs = DOCS[kind];
  const { data, error, refetch, startPolling, stopPolling } = useQuery(docs.query, {
    fetchPolicy: 'cache-and-network',
    skip: !enabled,
    // The read after an upload must not reuse one started before it (old ACTIVE state).
    context: { queryDeduplication: false },
  });
  const [requestUpload] = useMutation(docs.request);
  const [submitPicture] = useMutation(docs.submit);
  const [uploading, setUploading] = useState(false);
  const [localPreview, setLocalPreview] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [submission, setSubmission] = useState(0);
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);

  const picture: MyPicture | undefined = data?.myProfilePicture;
  const pending = picture?.latestStatus === 'PENDING';
  usePollWhile(pending, startPolling, stopPolling, POLL_MS, POLL_GIVE_UP_MS, String(submission));
  // A pull-to-refresh (or coming back to the screen) re-reads the review state.
  useEffect(() => {
    if (enabled && refreshKey > 0) refetch().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);
  useEffect(() => {
    if (!pending) setLocalPreview(null);
  }, [pending]);

  /** 'rules' when the community rules must be accepted first. */
  const pick = async (rulesJustAccepted = false): Promise<'rules' | void> => {
    if (!picture || uploading) return;
    if (pending) {
      // Polling gives up after a while: ask again before saying it's still in review.
      const { data: fresh } = await refetch().catch(() => ({ data: undefined }));
      if (fresh?.myProfilePicture?.latestStatus === 'PENDING') {
        setMessage('Todavía estamos revisando tu imagen. Inténtalo en un momento.');
        return;
      }
    }
    if (picture.rulesRequired && !rulesJustAccepted) return 'rules';
    if (picture.blockMessage && !(rulesJustAccepted && picture.rulesRequired)) {
      setMessage(picture.blockMessage);
      return;
    }
    let result;
    try {
      result = await pickFromLibrary({ mediaType: 'photo', selectionLimit: 1, quality: 0.8, ...docs.pick });
    } catch {
      setMessage('No pudimos abrir tu galería.');
      return;
    }
    if (result.errorCode) {
      setMessage('No pudimos abrir tu galería. Revisa el permiso de fotos en Ajustes.');
      return;
    }
    const asset = result.assets?.[0];
    if (result.didCancel || !asset?.uri) return;
    const type = asset.type === 'image/png' || asset.type === 'image/webp' ? asset.type : 'image/jpeg';
    setUploading(true);
    setMessage(null);
    try {
      const { data: upload } = await requestUpload({ variables: { contentType: type } });
      const ticket = upload?.[docs.requestField];
      if (!ticket?.success || !ticket.upload) throw new Error(ticket?.error || 'No pudimos subir tu imagen.');
      const fields = typeof ticket.upload.fields === 'string' ? JSON.parse(ticket.upload.fields) : ticket.upload.fields;
      await uploadFileToPresignedForm(ticket.upload.url, fields || {}, asset.uri, asset.fileName || 'imagen.jpg', type);
      const { data: submitted } = await submitPicture({ variables: { imageKey: ticket.upload.key } });
      const outcome = submitted?.[docs.submitField];
      if (!outcome?.success) throw new Error(outcome?.error || 'No pudimos enviar tu imagen.');
      if (!mounted.current) return;
      setLocalPreview(asset.uri);
      setSubmission((n) => n + 1);
      await refetch();
    } catch (e: any) {
      if (mounted.current) {
        setMessage(e?.message && !/network|graphql/i.test(e.message) ? e.message : 'No pudimos subir tu imagen. Revisa tu conexión.');
      }
    } finally {
      if (mounted.current) setUploading(false);
    }
  };

  const refused = picture?.latestStatus === 'REJECTED' || picture?.latestStatus === 'FAILED';
  return {
    available: enabled && !isSchemaMismatch(error) && Boolean(picture),
    url: pending && localPreview ? localPreview : picture?.url ?? null,
    pending,
    uploading,
    // What to tell the member: a refusal reason, an upload problem, or the review in progress.
    message: message ?? (refused ? picture?.latestReason || 'No se aprobó. Prueba con otra imagen.' : null),
    pick,
    refetch,
  };
}
