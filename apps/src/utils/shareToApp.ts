// Send a captured image straight to WhatsApp or Instagram. When the app is
// not installed, or the direct route fails, the phone's own share sheet
// opens instead, so the member is never stuck with a dead button.
//
// iOS is different on both (react-native-share's native code):
// - WhatsApp's direct route sends the image ALONE (UIDocumentInteraction
//   never reads `message`), which would drop the invite link the card's
//   signups are credited by. The system share sheet hands WhatsApp the image
//   and the text together, so iOS goes there.
// - Instagram opens instagram://library with a Photos asset id, not a file:
//   the card is saved to Photos first and its ph:// id is passed.
import { Platform } from 'react-native';
import { CameraRoll } from '@react-native-camera-roll/camera-roll';
import Share, { Social } from 'react-native-share';

export type ShareApp = 'whatsapp' | 'instagram';

const text = (e: unknown) => String((e as any)?.message ?? e ?? '');
const isCancel = (e: unknown) => /cancel|dismiss/i.test(text(e));

const openSheet = (uri: string, message: string, filename: string) =>
  Share.open({ url: uri, type: 'image/png', filename, message, failOnCancel: false });

export async function shareImageToApp(app: ShareApp, uri: string, message: string, filename: string): Promise<void> {
  if (Platform.OS === 'ios') {
    if (app === 'whatsapp') {
      await openSheet(uri, message, filename);
      return;
    }
    try {
      // Photos access denied or the save failed: the sheet below still works.
      const asset = await CameraRoll.save(uri, { type: 'photo' });
      await Share.shareSingle({ social: Social.Instagram, url: asset, type: 'image/png', filename });
    } catch (e) {
      // Not installed: the library already sent them to the App Store.
      if (isCancel(e) || /not installed/i.test(text(e))) return;
      await openSheet(uri, message, filename);
    }
    return;
  }
  try {
    await Share.shareSingle({
      social: app === 'whatsapp' ? Social.Whatsapp : Social.Instagram,
      url: uri,
      type: 'image/png',
      filename,
      // Instagram drops captions from shared images; WhatsApp keeps it.
      message: app === 'whatsapp' ? message : undefined,
    });
    return;
  } catch (e) {
    if (isCancel(e)) return;
  }
  await openSheet(uri, message, filename);
}
