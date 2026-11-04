// One way to send an investment share card anywhere: WhatsApp, Instagram,
// the phone's share sheet, or the gallery. Every tap is logged
// (inbox.ExternalShareTap), and the text carries the sharer's tagged invite
// link so the signup a share brings is credited to it.
import { useCallback } from 'react';
import { useMutation } from '@apollo/client';
import Share from 'react-native-share';

import { RECORD_EXTERNAL_SHARE } from '../apollo/mutations';
import { useAuth } from '../contexts/AuthContext';
import { saveImageToGallery } from '../utils/saveImageToGallery';
import { shareImageToApp } from '../utils/shareToApp';
import {
  composeShareMessage,
  shareCardLink,
  type ShareProduct,
  type ShareSurface,
  type ShareTarget,
} from '../utils/shareCardLink';

export type { ShareTarget } from '../utils/shareCardLink';

export function useShareCardDelivery(surface: ShareSurface) {
  const { userProfile } = useAuth() as any;
  const username: string | null = userProfile?.username || null;
  const [record] = useMutation(RECORD_EXTERNAL_SHARE);

  const messageFor = useCallback(
    (lead: string, target: ShareTarget, product: ShareProduct) =>
      composeShareMessage(lead, shareCardLink(username, { target, product, surface })),
    [username, surface],
  );

  /** Bookkeeping: never awaited, never surfaces an error. */
  const log = useCallback(
    (target: ShareTarget, product: ShareProduct, extra: { ticker?: string; reference?: string; showAmount?: boolean }) => {
      Promise.resolve()
        .then(() => record({
          variables: {
            surface, product, target,
            ticker: extra.ticker || null,
            reference: extra.reference || null,
            showAmount: Boolean(extra.showAmount),
          },
        }))
        .catch(() => undefined);
    },
    [record, surface],
  );

  /** Send a captured card. Throws only on a real failure (cancel is not one). */
  const deliver = useCallback(
    async (target: ShareTarget, uri: string, opts: {
      lead: string; product: ShareProduct; filename: string; title?: string;
      ticker?: string; reference?: string; showAmount?: boolean;
    }) => {
      log(target, opts.product, opts);
      if (target === 'save') {
        await saveImageToGallery(uri);
        return;
      }
      const message = messageFor(opts.lead, target, opts.product);
      if (target === 'whatsapp' || target === 'instagram') {
        await shareImageToApp(target, uri, message, opts.filename);
        return;
      }
      try {
        await Share.open({
          title: opts.title, message, url: uri, type: 'image/png', filename: opts.filename, failOnCancel: false,
        });
      } catch (e: any) {
        if (!/cancel|dismiss/i.test(String(e?.message ?? e ?? ''))) throw e;
      }
    },
    [log, messageFor],
  );

  return { deliver, messageFor, log };
}
