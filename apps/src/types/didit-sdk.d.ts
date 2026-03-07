declare module '@didit-protocol/sdk-react-native' {
  export function startVerification(sessionToken: string): Promise<any>;

  const DiditSdk: {
    startVerification?: (sessionToken: string) => Promise<any>;
  };

  export default DiditSdk;
}
