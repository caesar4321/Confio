package com.Confio.Confio

import android.view.WindowManager
import com.facebook.react.ReactPackage
import com.facebook.react.bridge.*
import com.facebook.react.uimanager.ViewManager

// Keeps a screen out of screenshots, screen recordings, casting and Recents
// (FLAG_SECURE) while it shows something only the person may see: the
// shopping task's live view of their signed-in store.
class ConfioSecureScreenPackage : ReactPackage {
    override fun createNativeModules(context: ReactApplicationContext): List<NativeModule> =
        listOf(ConfioSecureScreenModule(context))
    override fun createViewManagers(context: ReactApplicationContext): List<ViewManager<*, *>> = emptyList()
}

class ConfioSecureScreenModule(context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
    override fun getName() = "ConfioSecureScreen"

    @ReactMethod
    fun setSecure(secure: Boolean) {
        val activity = currentActivity ?: return
        activity.runOnUiThread {
            val window = activity.window ?: return@runOnUiThread
            if (secure) {
                window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
            } else {
                window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
            }
        }
    }
}
