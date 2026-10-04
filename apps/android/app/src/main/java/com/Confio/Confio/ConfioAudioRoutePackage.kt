package com.Confio.Confio

import android.content.Context
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Build
import android.view.HapticFeedbackConstants
import com.facebook.react.ReactPackage
import com.facebook.react.bridge.*
import com.facebook.react.uimanager.ViewManager

// Routes Confío IA voice calls to the loudspeaker (WebRTC uses the
// communication stream, which defaults to the earpiece).
class ConfioAudioRoutePackage : ReactPackage {
    override fun createNativeModules(context: ReactApplicationContext): List<NativeModule> = listOf(ConfioAudioRouteModule(context))
    override fun createViewManagers(context: ReactApplicationContext): List<ViewManager<*, *>> = emptyList()
}

class ConfioAudioRouteModule(private val context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
    override fun getName() = "ConfioAudioRoute"

    /** A light tap when hold-to-talk starts recording (no VIBRATE permission needed). */
    @ReactMethod
    fun impact() {
        val activity = currentActivity ?: return
        activity.runOnUiThread {
            activity.window?.decorView?.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
        }
    }

    @ReactMethod
    fun setSpeaker(on: Boolean, promise: Promise) {
        val audio = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        try {
            if (on) {
                audio.mode = AudioManager.MODE_IN_COMMUNICATION
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                    audio.availableCommunicationDevices
                        .firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER }
                        ?.let { audio.setCommunicationDevice(it) }
                } else {
                    @Suppress("DEPRECATION")
                    audio.isSpeakerphoneOn = true
                }
            } else {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                    audio.clearCommunicationDevice()
                } else {
                    @Suppress("DEPRECATION")
                    audio.isSpeakerphoneOn = false
                }
                audio.mode = AudioManager.MODE_NORMAL
            }
            promise.resolve(true)
        } catch (e: Exception) {
            promise.reject("AUDIO_ROUTE", "No pudimos cambiar el audio.", e)
        }
    }
}
