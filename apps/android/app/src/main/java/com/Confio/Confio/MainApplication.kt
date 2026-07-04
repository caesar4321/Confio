package com.Confio.Confio

import android.app.Application
import android.content.Context
import android.util.Log
import com.facebook.react.ReactApplication
import com.facebook.react.ReactHost
import com.facebook.react.ReactNativeHost
import com.facebook.react.ReactPackage
import com.facebook.react.defaults.DefaultNewArchitectureEntryPoint.load
import com.facebook.react.defaults.DefaultReactHost.getDefaultReactHost
import com.facebook.react.defaults.DefaultReactNativeHost
import com.facebook.react.modules.network.OkHttpClientProvider
import com.facebook.react.soloader.OpenSourceMergedSoMapping
import com.facebook.soloader.ExternalSoMapping
import com.facebook.soloader.SoLoader
import java.io.File

// Autolinked packages come from the generated PackageList; only packages
// that CANNOT autolink are imported manually below.
import com.facebook.react.PackageList
import com.Confio.Confio.MediaPickerPackage
import com.sdkreactnative.SdkReactNativePackage

class MainApplication : Application(), ReactApplication {

  override val reactNativeHost: ReactNativeHost =
      object : DefaultReactNativeHost(this) {
        override fun getPackages(): List<ReactPackage> {
          // PackageList includes MainReactPackage + every autolinked module
          // (react-native.config.js governs exclusions).
          return PackageList(this).packages.apply {
            // Manual: local in-app package (not an npm module)
            add(MediaPickerPackage())
            // Manual: Didit SDK (custom maven repo; excluded from autolinking)
            add(SdkReactNativePackage())
          }
        }

        override fun getJSMainModuleName(): String = "index"

        override fun getUseDeveloperSupport(): Boolean = BuildConfig.DEBUG

        override val isNewArchEnabled: Boolean = BuildConfig.IS_NEW_ARCHITECTURE_ENABLED
        override val isHermesEnabled: Boolean = BuildConfig.IS_HERMES_ENABLED
      }

  override val reactHost: ReactHost
    get() = getDefaultReactHost(applicationContext, reactNativeHost)

  override fun attachBaseContext(base: Context) {
    super.attachBaseContext(base)
    clearStaleSoLoaderBackupStore(base)
    // Initialize SoLoader as early as possible so the RN merged-so mapping
    // (libreact_featureflagsjni → libreactnative.so) is registered before any
    // ContentProvider, Activity, or static initializer can trigger
    // SoLoader.loadLibrary. Without this, certain devices (observed: MIUI/Xiaomi)
    // crash with UnsatisfiedLinkError "libreact_featureflagsjni.so not found".
    SoLoader.init(base, ConfioMergedSoMapping)
  }

  override fun onCreate() {
    super.onCreate()

    // Must be set before any ReactInstance is created so fetch/XHR/WebSocket/
    // image traffic all pick up the IPv4-first, bounded-connect client.
    OkHttpClientProvider.setOkHttpClientFactory(ConfioOkHttpClientFactory())

    if (BuildConfig.IS_NEW_ARCHITECTURE_ENABLED) {
      // If you opted-in for the New Architecture, we load the native entry point for this app.
      load()
    }
  }
}

private fun clearStaleSoLoaderBackupStore(context: Context) {
  try {
    val soLoaderBackupDir = File(context.applicationInfo.dataDir, "lib-main")
    if (soLoaderBackupDir.exists() && !soLoaderBackupDir.deleteRecursively()) {
      Log.w("MainApplication", "Unable to fully clear stale SoLoader backup store")
    }
  } catch (e: Throwable) {
    Log.w("MainApplication", "Failed to clear stale SoLoader backup store", e)
  }
}

private object ConfioMergedSoMapping : ExternalSoMapping {
  override fun mapLibName(input: String): String = OpenSourceMergedSoMapping.mapLibName(input)

  override fun invokeJniOnload(libraryName: String) {
    // RN 0.79 packages several JNI libraries inside libreactnative.so. The merged children
    // need explicit JNI_OnLoad dispatch, but "reactnative" itself is only the container.
    if (libraryName != "reactnative") {
      OpenSourceMergedSoMapping.invokeJniOnload(libraryName)
    }
  }
}
