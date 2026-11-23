// The floating Pagar button sits over the bottom-right of the screens opened
// from the drawer. With a tab bar gone, their lists run to the physical
// bottom: without this room the end of the last row (on Perfil, "Cerrar
// sesión") would sit under the button, and a tap there would open the scanner.
import { CONVERSATION_HOME_ENABLED } from '../config/features';
import { usePrimaryAction } from './usePrimaryAction';

// The button: 20 above the bottom of the screen (which the app's root already
// keeps above the system bar), 48 tall, and air above it.
export const FLOATING_BOTTOM = 20;
const BUTTON_ROOM = FLOATING_BOTTOM + 48 + 16;

/** Extra bottom padding for a list on one of those screens; 0 when there is no button. */
export function useFloatingPrimaryInset(): number {
  const primary = usePrimaryAction();
  if (!CONVERSATION_HOME_ENABLED || !primary) {
    return 0;
  }
  return BUTTON_ROOM;
}
