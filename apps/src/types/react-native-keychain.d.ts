declare module 'react-native-keychain' {
  export interface UserCredentials {
    username: string;
    password: string;
  }

  export interface Options {
    accessControl?: string;
    accessible?: string;
    authenticationType?: string;
    service?: string;
    username?: string;
  }

  export function getGenericPassword(options?: Options): Promise<false | UserCredentials>;
  export function setGenericPassword(username: string, password: string, options?: Options): Promise<boolean>;
  export function resetGenericPassword(options?: Options): Promise<boolean>;

  export function getInternetCredentials(server: string, options?: Options): Promise<false | UserCredentials>;
  export function setInternetCredentials(server: string, username: string, password: string, options?: Options): Promise<boolean>;
  export function resetInternetCredentials(server: string, options?: Options): Promise<boolean>;

  export const ACCESSIBLE: {
    WHEN_UNLOCKED: string;
    AFTER_FIRST_UNLOCK: string;
    ALWAYS: string;
    WHEN_PASSCODE_SET_THIS_DEVICE_ONLY: string;
    WHEN_UNLOCKED_THIS_DEVICE_ONLY: string;
    AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY: string;
    ALWAYS_THIS_DEVICE_ONLY: string;
  };
} 