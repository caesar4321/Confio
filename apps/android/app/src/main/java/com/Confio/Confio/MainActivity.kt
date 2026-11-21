package com.Confio.Confio

import com.facebook.react.ReactActivity
import com.facebook.react.ReactActivityDelegate
import com.facebook.react.defaults.DefaultNewArchitectureEntryPoint.fabricEnabled
import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.view.MotionEvent
import com.facebook.react.defaults.DefaultReactActivityDelegate

class MainActivity : ReactActivity() {

  /**
   * Returns the name of the main component registered from JavaScript. This is used to schedule
   * rendering of the component.
   */
  override fun getMainComponentName(): String = "Confio"

  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(null)
    // A share is handled when it arrives, never again when Android restores
    // the task (process death) or relaunches it from Recents.
    val fromHistory = ((intent?.flags ?: 0) and Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY) != 0
    if (savedInstanceState == null && !fromHistory) {
      ConfioShareIntentModule.handleIntent(intent)
    }
  }

  // singleTask: a share while the app is open arrives here.
  override fun onNewIntent(intent: Intent) {
    super.onNewIntent(intent)
    setIntent(intent)
    ConfioShareIntentModule.handleIntent(intent)
  }

  /**
   * Returns the instance of the [ReactActivityDelegate]. We use [DefaultReactActivityDelegate]
   * which allows you to enable New Architecture with a single boolean flags [fabricEnabled]
   */
  override fun createReactActivityDelegate(): ReactActivityDelegate =
      DefaultReactActivityDelegate(this, mainComponentName, fabricEnabled)

  override fun dispatchTouchEvent(ev: MotionEvent?): Boolean {
    return try {
      super.dispatchTouchEvent(ev)
    } catch (e: NullPointerException) {
      // Workaround for MIUI/Xiaomi system bug: miui.util.font.FontNameUtil.isNameOf
      // throws NPE when Paint.getTypeface() is called during hit-testing of styled text
      // (RN CustomStyleSpan). Swallow only this specific MIUI path; rethrow anything else.
      if (e.stackTrace.any { it.className.startsWith("miui.util.font") }) {
        Log.w("MainActivity", "Suppressed MIUI FontNameUtil NPE during touch dispatch", e)
        true
      } else {
        throw e
      }
    }
  }
}
