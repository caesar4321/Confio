// Finishing does not depend on the sheet: the lock can unmount it mid-request.
import type { ApolloClient } from '@apollo/client';

import { COMPLETE_CONNECT } from './api';
import { takeMailConnectResult } from './connectLink';
import { mailSession } from './session';
import { takeVerifier } from './verifier';

export function finishMailConnect(client: ApolloClient<any>, userId: string): Promise<void> | null {
  const session = mailSession(userId);
  const back = takeMailConnectResult();
  if (!back) {
    return session.finishing;
  }
  const work = (async () => {
    try {
      const verifier = await takeVerifier(userId, back.state);
      if (!verifier) {
        session.notice = 'Ese enlace no es de esta conexión o ya venció. Si no se conectó, vuelve a intentarlo.';
        return;
      }
      if ('denied' in back) {
        session.notice = 'No conectaste tu Gmail. No guardé nada.';
        return;
      }
      const { data } = await client.mutate<any>({
        mutation: COMPLETE_CONNECT,
        variables: { code: back.code, state: back.state, verifier },
        fetchPolicy: 'no-cache',
      });
      const result = data?.completeAssistantMailConnect;
      session.notice = result?.success ? 'Gmail conectado.' : result?.error || 'No pude conectar Gmail. Inténtalo de nuevo.';
    } catch {
      session.notice = 'No pude conectar Gmail. Inténtalo de nuevo.';
    }
  })().finally(() => {
    if (session.finishing === work) {
      session.finishing = null;
    }
  });
  session.finishing = work;
  return work;
}
