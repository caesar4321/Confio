import { ImageLibraryOptions, ImagePickerResponse, launchImageLibrary } from 'react-native-image-picker';

import { withSystemPicker } from './systemPickerGuard';

export { isSystemPickerOpen, SYSTEM_PICKER_MAX_MS, withSystemPicker } from './systemPickerGuard';

/** launchImageLibrary that does not trip the resume lock (see systemPickerGuard). */
export function pickFromLibrary(options: ImageLibraryOptions): Promise<ImagePickerResponse> {
  return withSystemPicker(() => launchImageLibrary(options));
}
