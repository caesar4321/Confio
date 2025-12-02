package com.Confio.Confio

import android.app.Application
import com.facebook.react.ReactApplication
import com.facebook.react.ReactHost
import com.facebook.react.ReactNativeHost
import com.facebook.react.ReactPackage
import com.facebook.react.defaults.DefaultNewArchitectureEntryPoint.load
import com.facebook.react.defaults.DefaultReactHost.getDefaultReactHost
import com.facebook.react.defaults.DefaultReactNativeHost
import com.facebook.react.soloader.OpenSourceMergedSoMapping
import com.facebook.soloader.SoLoader

// Manual imports for all packages
import com.RNAppleAuthentication.AppleAuthenticationAndroidPackage
import io.invertase.notifee.NotifeePackage
import com.reactnativecommunity.cameraroll.CameraRollPackage
import io.invertase.firebase.app.ReactNativeFirebaseAppPackage
import io.invertase.firebase.auth.ReactNativeFirebaseAuthPackage
import io.invertase.firebase.messaging.ReactNativeFirebaseMessagingPackage
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
import com.worklets.WorkletsPackage
import com.rt2zz.reactnativecontacts.ReactNativeContacts
import com.learnium.RNDeviceInfo.RNDeviceInfo
import com.Confio.Confio.MediaPickerPackage
import com.proyecto26.inappbrowser.RNInAppBrowserPackage

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
            WorkletsPackage(),
            ReactNativeContacts(),
            RNDeviceInfo(),
            MediaPickerPackage(),
            RNInAppBrowserPackage()
          )
        }

        override fun getJSMainModuleName(): String = "index"

        override fun getUseDeveloperSupport(): Boolean = BuildConfig.DEBUG

        override val isNewArchEnabled: Boolean = BuildConfig.IS_NEW_ARCHITECTURE_ENABLED
        override val isHermesEnabled: Boolean = BuildConfig.IS_HERMES_ENABLED
      }

  override val reactHost: ReactHost
    get() = getDefaultReactHost(applicationContext, reactNativeHost)

  override fun onCreate() {
    super.onCreate()
    SoLoader.init(this, OpenSourceMergedSoMapping)
    if (BuildConfig.IS_NEW_ARCHITECTURE_ENABLED) {
      // If you opted-in for the New Architecture, we load the native entry point for this app.
      load()
    }
  }
}
