/**
 * Leave a finished or abandoned P2P flow (trade chat, active trade, offer
 * creation) for Descubrir.
 *
 * Descubrir used to be a tab, so "go to Discover" dropped the user on the tab
 * shell. As a pushed screen, a plain navigate would stack it on top of the
 * flow — its back button then returns to the chat it just left, and repeating
 * that loops. A reset leaves exactly Inicio → Descubrir.
 */
export const exitToDiscover = (navigation: { reset: (state: any) => void }) => {
  navigation.reset({
    index: 1,
    routes: [{ name: 'BottomTabs' }, { name: 'Discover' }],
  });
};
