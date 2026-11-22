import { gql } from '@apollo/client';

export type CalendarKind = 'payment' | 'ticket' | 'trip' | 'deadline' | 'none';

// Its own document: an older server rejects only this.
export const ANALYZE_ASSISTANT_CALENDAR = gql`
  mutation AnalyzeAssistantCalendar($titles: [String!]!, $consentVersion: Int!) {
    analyzeAssistantCalendar(titles: $titles, consentVersion: $consentVersion) {
      success
      error
      errorCode
      kinds
    }
  }
`;

// Copy is written here, never by the model.
export const KIND_LABELS: Record<CalendarKind, string | null> = {
  payment: 'Parece un pago',
  ticket: 'Parece un pasaje o una entrada',
  trip: 'Parece un viaje',
  deadline: 'Parece un vencimiento',
  none: null,
};
