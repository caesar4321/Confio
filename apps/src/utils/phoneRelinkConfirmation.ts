// Server-issued proof that a verified phone belongs to other account(s);
// shown to the user by PhoneRelinkModal before the move is confirmed.
export type PhoneRelinkConfirmation = {
  token: string;
  accounts: Array<{ email: string; username: string }>;
};
