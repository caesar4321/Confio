// Push-to-talk voice notes for Confío IA: record → base64 → server
// transcribes (gpt-transcribe) and answers. The audio is never stored.
//
// On a build without the native recorder, `isVoiceNoteAvailable` is false
// and the mic button stays hidden instead of crashing.
import { NativeModules, PermissionsAndroid, Platform } from 'react-native';
import AudioRecorderPlayer, {
  AVEncoderAudioQualityIOSType,
  AVEncodingOption,
  AudioEncoderAndroidType,
  AudioSourceAndroidType,
  OutputFormatAndroidType,
} from 'react-native-audio-recorder-player';

// Android links native modules by hand in this project: check the module is
// really registered before offering the mic.
const sound = NativeModules.RNAudioRecorderPlayer ? new AudioRecorderPlayer() : null;

export const isVoiceNoteAvailable = !!sound;
export const MAX_VOICE_NOTE_MS = 120_000;

// Speech, not music: 16 kHz mono AAC keeps a 2-minute note well under 1 MB.
const AUDIO_SET = {
  AVFormatIDKeyIOS: AVEncodingOption.aac,
  AVSampleRateKeyIOS: 16000,
  AVNumberOfChannelsKeyIOS: 1,
  AVEncoderAudioQualityKeyIOS: AVEncoderAudioQualityIOSType.medium,
  AVEncoderBitRateKeyIOS: 32000,
  AudioSourceAndroid: AudioSourceAndroidType.MIC,
  OutputFormatAndroid: OutputFormatAndroidType.MPEG_4,
  AudioEncoderAndroid: AudioEncoderAndroidType.AAC,
  AudioSamplingRateAndroid: 16000,
  AudioChannelsAndroid: 1,
  AudioEncodingBitRateAndroid: 32000,
};

let startedAt = 0;
let recording = false;
let starting = false;
// Bumped by cancel: a start still waiting on permission or the native
// recorder must not turn the mic on afterwards.
let generation = 0;

async function ensureMicPermission(): Promise<boolean> {
  if (Platform.OS !== 'android') {
    return true; // iOS asks on first record (NSMicrophoneUsageDescription).
  }
  const granted = await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.RECORD_AUDIO, {
    title: 'Micrófono',
    message: 'Confío IA necesita el micrófono para escuchar tus audios.',
    buttonPositive: 'Permitir',
    buttonNegative: 'Ahora no',
  });
  return granted === PermissionsAndroid.RESULTS.GRANTED;
}

export async function startVoiceNote(onTick?: (ms: number) => void): Promise<boolean> {
  if (!sound || recording || starting) {
    return false;
  }
  const gen = ++generation;
  starting = true;
  try {
    if (!(await ensureMicPermission()) || gen !== generation) {
      return false;
    }
    if (onTick) {
      sound.addRecordBackListener?.((e: { currentPosition: number }) => onTick(e.currentPosition));
    }
    await sound.startRecorder(undefined, AUDIO_SET, false);
    if (gen !== generation) {
      // Cancelled while the recorder was starting: stop it right away.
      sound.removeRecordBackListener?.();
      await sound.stopRecorder().catch(() => {});
      return false;
    }
    startedAt = Date.now();
    recording = true;
    return true;
  } finally {
    starting = false;
  }
}

async function fileToBase64(uri: string): Promise<string> {
  const path = uri.startsWith('file://') ? uri : `file://${uri}`;
  const response = await fetch(path);
  const blob = await response.blob();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('No se pudo leer el audio'));
    reader.onloadend = () => {
      const result = String(reader.result || '');
      resolve(result.slice(result.indexOf(',') + 1));
    };
    reader.readAsDataURL(blob);
  });
}

export type VoiceNote = { base64: string; mimeType: string; durationMs: number };

export async function stopVoiceNote(): Promise<VoiceNote | null> {
  if (!sound || !recording) {
    return null;
  }
  recording = false;
  sound.removeRecordBackListener?.();
  const uri: string = await sound.stopRecorder();
  const durationMs = Math.min(Date.now() - startedAt, MAX_VOICE_NOTE_MS);
  if (durationMs < 600) {
    return null; // a tap, not a message
  }
  const base64 = await fileToBase64(uri);
  // Both platforms record AAC in an MPEG-4 container by default.
  return { base64, mimeType: 'audio/mp4', durationMs };
}

export async function cancelVoiceNote(): Promise<void> {
  generation += 1; // also cancels a start in progress
  if (!sound || !recording) {
    return;
  }
  recording = false;
  sound.removeRecordBackListener?.();
  try {
    await sound.stopRecorder();
  } catch {
    // already stopped
  }
}
