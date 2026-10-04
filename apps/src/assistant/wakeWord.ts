// "Confío" wake word (Assistant+), on-device with Picovoice Porcupine. Audio never
// leaves the phone until the keyword is heard; then a voice call starts.
// Only while the app is in the foreground (no background listening).
//
// Needs two things before it can run (both from the Picovoice Console):
//   - the AccessKey, served by the server only to Assistant+ users
//     (Secrets Manager prod/confio-assistant → picovoice_access_key)
//   - the trained Spanish keyword + model, bundled as app assets:
//       iOS:     ios/Confio/WakeWord/confio_es_ios.ppn, porcupine_params_es.pv
//       Android: android/app/src/main/assets/confio_es_android.ppn, porcupine_params_es.pv
// If either is missing, start() fails quietly and the setting stays off.
import { Platform } from 'react-native';

let PorcupineManager: any = null;
try {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  PorcupineManager = require('@picovoice/porcupine-react-native').PorcupineManager;
} catch {
  PorcupineManager = null;
}

const KEYWORD = Platform.OS === 'ios' ? 'confio_es_ios.ppn' : 'confio_es_android.ppn';
const MODEL = 'porcupine_params_es.pv';

export class WakeWordListener {
  private manager: any = null;
  private running = false;
  private released = false;
  // The state callers want; one serialized queue moves the engine there, so
  // start/stop/release can never interleave half-way.
  private wanted = false;
  private queue: Promise<void> = Promise.resolve();

  constructor(private accessKey: string, private onWake: () => void, private onError?: (message: string) => void) {}

  start(): Promise<boolean> {
    this.wanted = true;
    return this.reconcile().then(() => this.running);
  }

  stop(): Promise<void> {
    this.wanted = false;
    return this.reconcile();
  }

  async release() {
    this.released = true;
    this.wanted = false;
    await this.reconcile();
    const manager = this.manager;
    this.manager = null;
    try {
      await manager?.delete();
    } catch {}
  }

  private reconcile(): Promise<void> {
    this.queue = this.queue.then(() => this.apply()).catch(() => {});
    return this.queue;
  }

  private async apply() {
    const want = this.wanted && !this.released;
    if (want && !this.running) {
      if (!PorcupineManager) {
        return;
      }
      try {
        if (!this.manager) {
          this.manager = await PorcupineManager.fromKeywordPaths(
            this.accessKey,
            [KEYWORD],
            () => this.onWake(),
            (error: Error) => this.onError?.(error?.message || 'wake word error'),
            MODEL,
            [0.6],
          );
        }
        await this.manager.start();
        this.running = true;
      } catch (error: any) {
        this.onError?.(error?.message || 'wake word unavailable');
      }
    } else if (!want && this.running) {
      try {
        await this.manager?.stop();
      } catch {}
      this.running = false;
    }
    // A request that changed `wanted` while we were busy is already queued.
  }
}
