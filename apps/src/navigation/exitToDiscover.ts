/** Leave a completed or abandoned P2P flow at Inicio. (It used to land on
 *  Descubrir, which is no longer a tab: Comunidad lives inside Invertir.) */
export const exitToDiscover = (navigation: { reset: (state: any) => void }) => {
  navigation.reset({
    index: 0,
    routes: [{ name: 'BottomTabs', params: { screen: 'Home' } }],
  });
};
