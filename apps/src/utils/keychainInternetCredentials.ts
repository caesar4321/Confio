import * as Keychain from 'react-native-keychain';

const SOFT_CLEARED_USERNAME = '__confio_cleared__';
const SOFT_CLEARED_PASSWORD = '__confio_null__';

type InternetCredentialsLike = {
  username?: string;
  password?: string;
} | false | null | undefined;

export function hasUsableInternetCredentials(
  credentials: InternetCredentialsLike
): credentials is { username?: string; password: string } {
  return Boolean(
    credentials &&
    typeof credentials.password === 'string' &&
    credentials.password.length > 0 &&
    credentials.password !== SOFT_CLEARED_PASSWORD
  );
}

export async function softClearInternetCredentials(server: string): Promise<void> {
  await Keychain.setInternetCredentials(
    server,
    SOFT_CLEARED_USERNAME,
    SOFT_CLEARED_PASSWORD
  );
}
