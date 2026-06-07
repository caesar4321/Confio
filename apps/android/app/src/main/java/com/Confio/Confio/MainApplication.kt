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
import com.facebook.react.soloader.OpenSourceMergedSoMapping
import com.facebook.soloader.ExternalSoMapping
import com.facebook.soloader.SoLoader
import java.io.File

// Manual imports for all packages
import com.RNAppleAuthentication.AppleAuthenticationAndroidPackage
import io.invertase.notifee.NotifeePackage
import com.reactnativecommunity.cameraroll.CameraRollPackage
import io.invertase.firebase.app.ReactNativeFirebaseAppPackage
import io.invertase.firebase.auth.ReactNativeFirebaseAuthPackage
import io.invertase.firebase.messaging.ReactNativeFirebaseMessagingPackage
import io.invertase.firebase.analytics.ReactNativeFirebaseAnalyticsPackage
import io.invertase.firebase.crashlytics.ReactNativeFirebaseCrashlyticsPackage
import io.invertase.firebase.appcheck.ReactNativeFirebaseAppCheckPackage
import com.reactnativegooglesignin.RNGoogleSigninPackage
import org.linusu.RNGetRandomValuesPackage
import com.oblador.keychain.KeychainPackage
import com.swmansion.reanimated.ReanimatedPackage
import com.th3rdwave.safeareacontext.SafeAreaContextPackage
import com.swmansion.rnscreens.RNScreensPackage
import com.horcrux.svg.SvgPackage
import com.oblador.vectoricons.VectorIconsPackage
import fr.greweb.reactnativeviewshot.RNViewShotPackage
import com.mrousavy.camera.react.CameraPackage
import com.worklets.WorkletsCorePackage
import com.rt2zz.reactnativecontacts.ReactNativeContacts
import com.learnium.RNDeviceInfo.RNDeviceInfo
import com.Confio.Confio.MediaPickerPackage
import cl.json.RNSharePackage
import com.sdkreactnative.SdkReactNativePackage
import com.reactnativecommunity.clipboard.ClipboardPackage

import com.uerceg.play_install_referrer.PlayInstallReferrerPackage

class MainApplication : Application(), ReactApplication {

  override val reactNativeHost: ReactNativeHost =
      object : DefaultReactNativeHost(this) {
        override fun getPackages(): List<ReactPackage> {
          return listOf(
            // Core React Native packages
            com.facebook.react.shell.MainReactPackage(),
            
            // Manual package list
            AppleAuthenticationAndroidPackage(),
            NotifeePackage(),
            CameraRollPackage(),
            ReactNativeFirebaseAppPackage(),
            ReactNativeFirebaseAuthPackage(),
            ReactNativeFirebaseMessagingPackage(),
            ReactNativeFirebaseAnalyticsPackage(),
            ReactNativeFirebaseCrashlyticsPackage(),
            ReactNativeFirebaseAppCheckPackage(),
            RNGoogleSigninPackage(),
            RNGetRandomValuesPackage(),
            KeychainPackage(),
            ReanimatedPackage(),
            SafeAreaContextPackage(),
            RNScreensPackage(),
            SvgPackage(),
            VectorIconsPackage(),
            RNViewShotPackage(),
            CameraPackage(),
            WorkletsCorePackage(),
            ReactNativeContacts(),
            RNDeviceInfo(),
            MediaPickerPackage(),
            RNSharePackage(),
            ClipboardPackage(),
            SdkReactNativePackage(),

            PlayInstallReferrerPackage()
          )
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
