package com.Confio.Confio

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.ui.graphics.Color
import androidx.core.content.ContextCompat
import com.amplifyframework.auth.AWSCredentials
import com.amplifyframework.auth.AWSCredentialsProvider
import com.amplifyframework.auth.AuthException
import com.amplifyframework.core.Consumer
import com.amplifyframework.ui.liveness.ui.FaceLivenessDetector
import com.facebook.react.ReactPackage
import com.facebook.react.bridge.*
import com.facebook.react.uimanager.ViewManager

class FaceLivenessPackage : ReactPackage {
    override fun createNativeModules(context: ReactApplicationContext): List<NativeModule> =
        listOf(FaceLivenessModule(context))

    override fun createViewManagers(context: ReactApplicationContext): List<ViewManager<*, *>> = emptyList()
}

/**
 * Runs one AWS Rekognition Face Liveness capture. The session and the
 * short-lived, single-action credentials come from the Confío backend
 * (startFaceCheck); grading happens server-side (completeFaceCheck), so this
 * only reports whether the capture finished.
 */
class FaceLivenessModule(private val context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
    override fun getName() = "ConfioFaceLiveness"

    @ReactMethod
    fun start(sessionId: String, region: String, credentials: ReadableMap, promise: Promise) {
        val activity = context.currentActivity
        if (activity == null) {
            promise.reject("no_activity", "No active screen")
            return
        }
        synchronized(FaceLivenessModule) {
            if (pending != null) {
                promise.reject("busy", "A face check is already running")
                return
            }
            pending = promise
        }
        val intent = Intent(activity, FaceLivenessActivity::class.java)
            .putExtra(EXTRA_SESSION, sessionId)
            .putExtra(EXTRA_REGION, region)
            .putExtra(EXTRA_ACCESS_KEY, credentials.getString("accessKeyId"))
            .putExtra(EXTRA_SECRET_KEY, credentials.getString("secretAccessKey"))
            .putExtra(EXTRA_SESSION_TOKEN, credentials.getString("sessionToken"))
            .putExtra(EXTRA_EXPIRATION, credentials.getDouble("expirationEpochSeconds").toLong())
        activity.startActivity(intent)
    }

    companion object {
        const val EXTRA_SESSION = "sessionId"
        const val EXTRA_REGION = "region"
        const val EXTRA_ACCESS_KEY = "accessKeyId"
        const val EXTRA_SECRET_KEY = "secretAccessKey"
        const val EXTRA_SESSION_TOKEN = "sessionToken"
        const val EXTRA_EXPIRATION = "expiration"

        private var pending: Promise? = null

        fun settle(code: String?, message: String?) {
            val promise = synchronized(FaceLivenessModule) { pending.also { pending = null } } ?: return
            if (code == null) promise.resolve("complete") else promise.reject(code, message ?: code)
        }
    }
}

class FaceLivenessActivity : ComponentActivity() {
    private var settled = false

    private fun settle(code: String?, message: String?) {
        if (settled) return
        settled = true
        FaceLivenessModule.settle(code, message)
        finish()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val extras = intent.extras
        val sessionId = extras?.getString(FaceLivenessModule.EXTRA_SESSION)
        val region = extras?.getString(FaceLivenessModule.EXTRA_REGION)
        val credentials = AWSCredentials.createAWSCredentials(
            extras?.getString(FaceLivenessModule.EXTRA_ACCESS_KEY),
            extras?.getString(FaceLivenessModule.EXTRA_SECRET_KEY),
            extras?.getString(FaceLivenessModule.EXTRA_SESSION_TOKEN),
            extras?.getLong(FaceLivenessModule.EXTRA_EXPIRATION),
        )
        if (sessionId == null || region == null || credentials == null) {
            settle("bad_arguments", "Missing session or credentials")
            return
        }
        val provider = object : AWSCredentialsProvider<AWSCredentials> {
            override fun fetchAWSCredentials(onSuccess: Consumer<AWSCredentials>, onError: Consumer<AuthException>) {
                onSuccess.accept(credentials)
            }
        }
        // The liveness view does not ask for the camera itself: without the
        // grant it would fail as a capture error instead of explaining why.
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            showDetector(sessionId, region, provider)
        } else {
            registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
                if (granted) showDetector(sessionId, region, provider)
                else settle("camera_permission_denied", "Camera permission denied")
            }.launch(Manifest.permission.CAMERA)
        }
    }

    private fun showDetector(sessionId: String, region: String, provider: AWSCredentialsProvider<AWSCredentials>) {
        setContent {
            MaterialTheme(colorScheme = lightColorScheme(primary = Color(0xFF10B981), onPrimary = Color.White)) {
                FaceLivenessDetector(
                    sessionId = sessionId,
                    region = region,
                    credentialsProvider = provider,
                    // Confío shows its own intro (including the flashing-light notice).
                    disableStartView = true,
                    onComplete = { settle(null, null) },
                    onError = { error -> settle(error.javaClass.simpleName, error.message) },
                )
            }
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        settle("UserCancelledException", "Cancelled")
        @Suppress("DEPRECATION")
        super.onBackPressed()
    }

    override fun onDestroy() {
        settle("UserCancelledException", "Cancelled")
        super.onDestroy()
    }
}
