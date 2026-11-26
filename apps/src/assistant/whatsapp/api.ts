import { gql } from '@apollo/client';

// Own documents, all named *WhatsApp*: an older server rejects only these (the row just doesn't
// show), and the request logs redact on the name.
// 1: links as a device, reads the chat list (not the chats), keeps important ones (7 days in v1), sends only
// what the person approves. 2: the person types the number, and one note goes to their own chat once linked.
// 3: linked from Confío's own servers; new messages of personal chats arrive as they come, never "en línea".
// 4: each chat's last 48 hours (both sides, hers from her phone too) kept encrypted as context.
// 5: each chat's last 30 days kept encrypted, and she can ask the assistant about them. The server takes 4 and 5
// and still reports 4 as its text, so a build on 4 keeps linking; a number above this one means "update".
// The text is consentText() and CONSENT_DATA in rules.ts: change them together.
export const WHATSAPP_CONSENT_VERSION = 5;

export type WhatsAppState = 'none' | 'pairing' | 'linked' | 'gone' | 'failed';

export type WhatsAppNotice = {
  id: string;
  kind: string;
  chat: string;
  preview: string;
  summary: string;
  time: string;
  createdAt: string;
};

export type WhatsAppLink = {
  state: WhatsAppState;
  code: string | null;
  codeAt: string | null;
  phoneHint: string | null;
  reason: string | null;
  reasonMessage: string | null;
  linkedAt: string | null;
  lastSyncAt: string | null;
  ownPhoneHint: string | null;
  suggestedPhone: string | null;
  consentVersion: number;
  consentOutdated: boolean;
  notices: WhatsAppNotice[];
};

export type WhatsAppDraft = {
  id: string;
  chat: string | null;
  phone: string | null;
  body: string;
  status: 'draft' | 'sending' | 'sent' | 'unknown' | 'failed';
  reason: string | null;
  displayHash: string;
};

const LINK = `state code codeAt phoneHint reason reasonMessage linkedAt lastSyncAt ownPhoneHint suggestedPhone consentVersion
  consentOutdated notices { id kind chat preview summary time createdAt }`;
const DRAFT = 'id chat phone body status reason displayHash';

export const GET_WHATSAPP = gql`
  query GetWhatsAppLink {
    whatsAppLink { ${LINK} }
  }
`;

export const START_WHATSAPP_LINK = gql`
  mutation StartWhatsAppLink($phone: String!, $consentVersion: Int!, $country: String) {
    startWhatsAppLink(phone: $phone, consentVersion: $consentVersion, country: $country) { success error errorCode }
  }
`;

export const UNLINK_WHATSAPP = gql`
  mutation UnlinkWhatsApp {
    unlinkWhatsApp { success error errorCode }
  }
`;

export const REFRESH_WHATSAPP = gql`
  mutation RefreshWhatsApp {
    refreshWhatsApp { success queued }
  }
`;

export const ACCEPT_WHATSAPP_CONSENT = gql`
  mutation AcceptWhatsAppConsent($consentVersion: Int!) {
    acceptWhatsAppConsent(consentVersion: $consentVersion) { success error errorCode }
  }
`;

export const DISMISS_WHATSAPP_NOTICE = gql`
  mutation DismissWhatsAppNotice($id: ID!) {
    dismissWhatsAppNotice(id: $id) { success error errorCode }
  }
`;

export const CREATE_WHATSAPP_DRAFT = gql`
  mutation CreateWhatsAppDraft($noticeId: ID, $body: String) {
    createWhatsAppDraft(noticeId: $noticeId, body: $body) { success error errorCode draft { ${DRAFT} } }
  }
`;

export const SEND_WHATSAPP_DRAFT = gql`
  mutation SendWhatsAppDraft($id: ID!, $displayHash: String!) {
    sendWhatsAppDraft(id: $id, displayHash: $displayHash) { success error errorCode draft { ${DRAFT} } }
  }
`;

export const GET_WHATSAPP_DRAFT = gql`
  query GetWhatsAppDraft($id: ID!) {
    whatsAppDraft(id: $id) { ${DRAFT} }
  }
`;

// A reply in the Confío IA conversation, on a card the person sends with a tap: a suggested reply as it is
// (body), or what she wrote in "Otro" for the assistant to write in full (instructions).
export const PREPARE_WHATSAPP_REPLY = gql`
  mutation PrepareWhatsAppReply($noticeId: ID!, $body: String, $instructions: String) {
    prepareWhatsAppReply(noticeId: $noticeId, body: $body, instructions: $instructions) {
      success error errorCode draft { ${DRAFT} }
    }
  }
`;
