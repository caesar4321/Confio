package com.Confio.Confio

import android.content.Intent
import android.net.Uri
import android.os.Build
import com.facebook.react.ReactPackage
import com.facebook.react.bridge.NativeModule
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.modules.core.DeviceEventManagerModule
import com.facebook.react.uimanager.ViewManager
import java.io.File
import java.lang.ref.WeakReference

/**
 * "Compartir → Confío" for an image (a store's or app's payment QR, a
 * screenshot). The activity hands the shared image here; JS copies it out,
 * reads the QR and opens the same Pagar flow as a scan. Nothing is paid here:
 * the person still reviews and confirms on the payment screen.
 */
class ConfioShareIntentModule(private val reactContext: ReactApplicationContext) :
  ReactContextBaseJavaModule(reactContext) {

  companion object {
    private const val EVENT = "ConfioSharedImage"
    private const val MAX_BYTES = 20L * 1024 * 1024

    @Volatile private var pending: Uri? = null
    @Volatile private var current: WeakReference<ConfioShareIntentModule>? = null

    /** Called by MainActivity for its launch intent and every new intent. */
    fun handleIntent(intent: Intent?) {
      if (intent == null || intent.action != Intent.ACTION_SEND) return
      if (intent.type?.startsWith("image/") != true) return
      // The extras come from another app: a malformed bundle must never crash Confío.
      val uri: Uri? = try {
        // The typed overload is unreliable on API 33; use it from 34 on.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
          intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
        } else {
          @Suppress("DEPRECATION")
          intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)
        }
      } catch (e: Exception) {
        null
      }
      // Delivered once: a recreated activity must not open the same share again.
      intent.action = Intent.ACTION_MAIN
      if (uri == null) return
      pending = uri
      current?.get()?.notifyJs()
    }
  }

  init {
    current = WeakReference(this)
  }

  override fun getName(): String = "ConfioShareIntent"

  private fun notifyJs() {
    if (reactContext.hasActiveReactInstance()) {
      reactContext
        .getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java)
        .emit(EVENT, null)
    }
  }

  /** The shared image copied to the app's cache (file:// uri), or null. */
  @ReactMethod
  fun consumeSharedImage(promise: Promise) {
    val uri = pending
    if (uri == null) {
      promise.resolve(null)
      return
    }
    pending = null
    Thread {
      // Only the newest share is ever read: earlier copies (screenshots of
      // checkouts and bank apps) do not stay in the cache.
      reactContext.cacheDir.listFiles { f -> f.name.startsWith("shared-qr-") }?.forEach { it.delete() }
      try {
        val file = File(reactContext.cacheDir, "shared-qr-${System.currentTimeMillis()}")
        val input = reactContext.contentResolver.openInputStream(uri)
          ?: throw IllegalStateException("Shared image is not readable")
        input.use { source ->
          file.outputStream().use { target ->
            val buffer = ByteArray(64 * 1024)
            var total = 0L
            while (true) {
              val read = source.read(buffer)
              if (read < 0) break
              total += read
              if (total > MAX_BYTES) throw IllegalStateException("Shared image is too large")
              target.write(buffer, 0, read)
            }
          }
        }
        promise.resolve(Uri.fromFile(file).toString())
      } catch (e: Exception) {
        promise.reject("SHARE_READ_FAILED", e.message, e)
      }
    }.start()
  }

  /** The copy is only for reading the QR: removed as soon as that is done. */
  @ReactMethod
  fun releaseSharedImage(uri: String) {
    val path = Uri.parse(uri).path ?: return
    val file = File(path)
    if (file.parentFile == reactContext.cacheDir && file.name.startsWith("shared-qr-")) file.delete()
  }

  @ReactMethod
  fun addListener(eventName: String) {}

  @ReactMethod
  fun removeListeners(count: Double) {}
}

class ConfioShareIntentPackage : ReactPackage {
  override fun createNativeModules(reactContext: ReactApplicationContext): MutableList<NativeModule> =
    mutableListOf(ConfioShareIntentModule(reactContext))

  override fun createViewManagers(reactContext: ReactApplicationContext): MutableList<ViewManager<*, *>> =
    mutableListOf()
}
