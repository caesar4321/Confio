/** What a Pagar review was prepared for. A send is signed only for exactly
 *  that: the same dollars, the same recipient and the same exact local amount
 *  (typed, or a fixed-amount QR's own; '' for a plain dollar send). */
export interface ReviewTerms {
  amount: string;
  destinationId: string;
  exactLocal: string;
}

export function reviewStillMatches(reviewed: ReviewTerms | null, current: ReviewTerms): boolean {
  return Boolean(reviewed)
    && reviewed!.amount === current.amount
    && reviewed!.destinationId === current.destinationId
    && reviewed!.exactLocal === current.exactLocal;
}

/** A server that predates a new mode answers with a schema error: say so in
 *  words (that mode is not available yet); anything else is worth a retry. */
export function isUnsupportedMode(error: any): boolean {
  return /Cannot query field|Unknown argument|Unknown type/i.test(String(error?.message || ''));
}
