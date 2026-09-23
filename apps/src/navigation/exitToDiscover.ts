/** Leave a completed or abandoned P2P flow at the Descubrir tab. */
export const exitToDiscover = (navigation: { reset: (state: any) => void }) => {
  navigation.reset({
    index: 0,
    routes: [{ name: 'BottomTabs', params: { screen: 'Discover' } }],
  });
};
