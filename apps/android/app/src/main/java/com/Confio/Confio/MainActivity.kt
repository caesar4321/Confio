package com.Confio.Confio

import com.facebook.react.ReactActivity
import com.facebook.react.ReactActivityDelegate
import com.facebook.react.defaults.DefaultNewArchitectureEntryPoint.fabricEnabled
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
