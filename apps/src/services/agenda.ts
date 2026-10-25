import { gql } from '@apollo/client';
import { useAccount } from '../contexts/AccountContext';

// Agenda: saved accounts, the person's own and other people's. Its own operations: an older
// server without these fields fails only the Agenda, never a shared query. Mis cuentas rows
// (rail "bank_info") are still added, edited and deleted with the BankInfo mutations.

const ENTRY_FIELDS = `
  id rail country relationship label holderName subtitle isDefault
  cedula phone bankCode bankInfoId destinationId
`;

export const AGENDA_ENTRIES = gql`query AgendaEntries {
  agendaEntries { ${ENTRY_FIELDS} }
}`;

export const AGENDA_RECENTS = gql`query AgendaRecents {
  agendaRecents { destinationId rail country label holderName }
}`;

export const SAVE_VE_AGENDA_ENTRY = gql`mutation SaveVePagomovilAgendaEntry(
  $id: String, $label: String, $relationship: String, $holderName: String,
  $cedula: String, $phone: String!, $bankCode: String!
) {
  saveVePagomovilAgendaEntry(
    id: $id, label: $label, relationship: $relationship, holderName: $holderName,
    cedula: $cedula, phone: $phone, bankCode: $bankCode
  ) { success errors entry { ${ENTRY_FIELDS} } }
}`;

export const SAVE_DESTINATION_TO_AGENDA = gql`mutation SaveDestinationToAgenda(
  $destinationId: String!, $label: String, $relationship: String
) {
  saveDestinationToAgenda(destinationId: $destinationId, label: $label, relationship: $relationship) {
    success errors entry { ${ENTRY_FIELDS} }
  }
}`;

export const UPDATE_AGENDA_ENTRY = gql`mutation UpdateAgendaEntry($id: String!, $label: String!, $relationship: String) {
  updateAgendaEntry(id: $id, label: $label, relationship: $relationship) { success errors entry { ${ENTRY_FIELDS} } }
}`;

export const DELETE_AGENDA_ENTRY = gql`mutation DeleteAgendaEntry($id: String!) {
  deleteAgendaEntry(id: $id) { success errors }
}`;

export type AgendaRelationship = 'own' | 'third_party';

export interface AgendaEntry {
  id: string;
  rail: string;
  country: string;
  relationship: AgendaRelationship;
  label: string;
  holderName: string;
  subtitle: string;
  isDefault: boolean;
  cedula?: string | null;
  phone?: string | null;
  bankCode?: string | null;
  bankInfoId?: string | null;
  destinationId?: string | null;
}

export interface AgendaRecent {
  destinationId: string;
  rail: string;
  country: string;
  label: string;
  holderName: string;
}

export const VE_PAGOMOVIL_RAIL = 've_pagomovil';
export const BANK_INFO_RAIL = 'bank_info';

/** Rails where someone else's account may be saved (Koywe "Mis cuentas" is own only). */
export const allowsThirdParty = (rail: string) => rail !== BANK_INFO_RAIL;

export const RAIL_NAMES: Record<string, string> = {
  ve_pagomovil: 'Pago Móvil',
  co_breb: 'Llave Bre-B',
  mx_clabe: 'CLABE',
  ar_cvu: 'CVU / Alias',
  br_pix: 'Pix',
  bank_info: 'Cuenta para retiros',
};

/** "58" + 10 digits → "0414 1234567" for display and editing. */
export const localVePhone = (phone?: string | null) => {
  const digits = String(phone || '').replace(/\D/g, '');
  const local = digits.startsWith('58') && digits.length === 12 ? `0${digits.slice(2)}` : digits;
  return local.length === 11 ? `${local.slice(0, 4)} ${local.slice(4)}` : local;
};

/**
 * The account the Agenda belongs to, or null while an account switch is
 * still exchanging tokens (a query then would answer for the previous one).
 */
export function useAgendaAccountKey(): string | null {
  const { activeAccount, isLoading } = useAccount();
  return isLoading ? null : (activeAccount?.id ?? null);
}

export const AGENDA_METHODS = gql`query AgendaMethods {
  agendaMethods { id kind country title subtitle allowsThirdParty status reason paymentMethodId }
}`;

/** An account type that can be added, from the server's rail registry. */
export interface AgendaMethod {
  id: string;
  kind: 've_pagomovil' | 'local' | 'bank_info' | string;
  country: string;
  title: string;
  subtitle: string;
  allowsThirdParty: boolean;
  status: string;
  reason: string;
  paymentMethodId?: string | null;
}

/** What to type for each local rail when saving it in the Agenda. */
export const LOCAL_FIELD_COPY: Record<string, { label: string; placeholder: string; keyboard?: 'default' | 'number-pad' }> = {
  co_breb: { label: 'Llave Bre-B', placeholder: 'Celular, cédula, correo o alias' },
  br_pix: { label: 'Chave Pix', placeholder: 'CPF, celular, e-mail o clave aleatoria' },
  mx_clabe: { label: 'CLABE', placeholder: '18 dígitos', keyboard: 'number-pad' },
  ar_cvu: { label: 'CVU o CBU', placeholder: '22 dígitos', keyboard: 'number-pad' },
};

/** The person's verified Venezuelan cédula ('' without one). */
export const AGENDA_OWN_VE_CEDULA = gql`query AgendaOwnVeCedula { agendaOwnVeCedula }`;

/** Same person: compare digits only (V/E is how banks write it). */
export const sameCedula = (a?: string | null, b?: string | null) => {
  const left = String(a || '').replace(/\D/g, '');
  return !!left && left === String(b || '').replace(/\D/g, '');
};
