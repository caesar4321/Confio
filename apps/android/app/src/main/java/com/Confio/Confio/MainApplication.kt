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
import com.facebook.react.shell.MainReactPackage
import com.swmansion.rnscreens.RNScreensPackage
import com.th3rdwave.safeareacontext.SafeAreaContextPackage
import com.mrousavy.camera.react.CameraPackage
import fr.greweb.reactnativeviewshot.RNViewShotPackage
import com.reactnativecommunity.cameraroll.CameraRollPackage
import com.rt2zz.reactnativecontacts.ReactNativeContacts
import io.invertase.firebase.messaging.ReactNativeFirebaseMessagingPackage
import com.learnium.RNDeviceInfo.RNDeviceInfo
import io.invertase.notifee.NotifeePackage
import com.proyecto26.inappbrowser.RNInAppBrowserPackage
import io.invertase.firebase.app.ReactNativeFirebaseAppPackage
import io.invertase.firebase.auth.ReactNativeFirebaseAuthPackage
import com.reactnativegooglesignin.RNGoogleSigninPackage
import org.linusu.RNGetRandomValuesPackage
import com.oblador.keychain.KeychainPackage
import com.oblador.vectoricons.VectorIconsPackage
import com.horcrux.svg.SvgPackage
import com.worklets.WorkletsPackage

class MainApplication : Application(), ReactApplication {

  override val reactNativeHost: ReactNativeHost =
      object : DefaultReactNativeHost(this) {
        override fun getPackages(): List<ReactPackage> =
            listOf(
              MainReactPackage(),
              ReactNativeFirebaseAppPackage(),
              ReactNativeFirebaseAuthPackage(),
              RNGoogleSigninPackage(),
              RNGetRandomValuesPackage(),
              KeychainPackage(),
              VectorIconsPackage(),
              SvgPackage(),
              WorkletsPackage(),
              RNScreensPackage(),
              SafeAreaContextPackage(),
              CameraPackage(),
              RNViewShotPackage(),
              CameraRollPackage(),
              ReactNativeContacts(),
              ReactNativeFirebaseMessagingPackage(),
              RNDeviceInfo(),
              NotifeePackage(),
              RNInAppBrowserPackage()
            )

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
