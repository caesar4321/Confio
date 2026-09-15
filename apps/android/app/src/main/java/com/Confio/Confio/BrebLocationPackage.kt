package com.Confio.Confio

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Base64
import androidx.core.content.ContextCompat
import com.facebook.react.ReactPackage
import com.facebook.react.bridge.*
import com.facebook.react.uimanager.ViewManager
import com.google.android.play.core.integrity.IntegrityManagerFactory
import com.google.android.play.core.integrity.StandardIntegrityManager
import com.google.android.gms.tasks.Task
import org.json.JSONObject
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean

class BrebLocationPackage : ReactPackage {
    override fun createNativeModules(context: ReactApplicationContext): List<NativeModule> = listOf(BrebLocationModule(context))
    override fun createViewManagers(context: ReactApplicationContext): List<ViewManager<*, *>> = emptyList()
}

class BrebLocationModule(private val context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
    override fun getName() = "BrebLocation"
    private var prepared: Task<StandardIntegrityManager.StandardIntegrityTokenProvider>? = null
    private var preparedProject: Long? = null

    @Synchronized
    private fun prepare(project: Long): Task<StandardIntegrityManager.StandardIntegrityTokenProvider> {
        if (preparedProject != project || prepared == null || (prepared!!.isComplete && !prepared!!.isSuccessful)) {
            preparedProject = project
            prepared = IntegrityManagerFactory.createStandard(context).prepareIntegrityToken(
                StandardIntegrityManager.PrepareIntegrityTokenRequest.builder().setCloudProjectNumber(project).build())
        }
        return prepared!!
    }

    @Synchronized
    private fun invalidate(task: Task<StandardIntegrityManager.StandardIntegrityTokenProvider>) {
        if (prepared === task) prepared = null
    }

    @ReactMethod
    fun attest(challenge: String, cloudProjectNumber: String, promise: Promise) {
        val project = cloudProjectNumber.toLongOrNull()
        if (project == null || project <= 0) {
            promise.reject("INTEGRITY_CONFIG", "La verificación del dispositivo aún no está disponible.")
            return
        }
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            promise.reject("LOCATION_PERMISSION", "Activa la ubicación precisa para solicitar Bre-B.")
            return
        }
        val manager = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager
        val handler = Handler(Looper.getMainLooper())
        val done = AtomicBoolean(false)
        val received = AtomicBoolean(false)
        // Reuse the prepared provider, not a token or a previous verdict.
        val provider = try {
            prepare(project)
        } catch (_: Exception) {
            promise.reject("INTEGRITY_FAILED", "No pudimos verificar el dispositivo. Vuelve a intentarlo.")
            return
        }
        lateinit var listener: LocationListener
        val timeout = Runnable {
            manager.removeUpdates(listener)
            // A task that never completed cannot remain cached forever.
            if (!provider.isComplete) invalidate(provider)
            if (done.compareAndSet(false, true)) promise.reject("LOCATION_TIMEOUT", "No pudimos verificar tu ubicación. Vuelve a intentarlo.")
        }
        listener = object : LocationListener {
            override fun onLocationChanged(location: Location) {
                if (received.get() || done.get()) return
                val mocked = if (Build.VERSION.SDK_INT >= 31) location.isMock else location.isFromMockProvider
                val ageMs = (SystemClock.elapsedRealtimeNanos() - location.elapsedRealtimeNanos) / 1000000
                if (mocked) {
                    manager.removeUpdates(this)
                    handler.removeCallbacks(timeout)
                    if (done.compareAndSet(false, true)) promise.reject("LOCATION_UNTRUSTED", "Necesitamos una ubicación precisa y sin simulación.")
                    return
                }
                // GPS often starts with a coarse or old fix. Keep waiting within
                // the original deadline instead of making the user retry.
                if (!location.hasAccuracy() || !location.accuracy.isFinite() ||
                    location.accuracy <= 0 || location.accuracy > 100 || ageMs < 0 || ageMs > 120000 ||
                    !location.latitude.isFinite() || !location.longitude.isFinite()) return
                if (!received.compareAndSet(false, true)) return
                manager.removeUpdates(this)
                val payload = JSONObject().put("latitude", location.latitude).put("longitude", location.longitude)
                    .put("accuracy", location.accuracy.toDouble()).put("timestamp", location.time).put("mocked", mocked).toString()
                val digest = MessageDigest.getInstance("SHA-256").digest((challenge + "." + payload).toByteArray(Charsets.UTF_8))
                val requestHash = Base64.encodeToString(digest, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
                provider.onSuccessTask { tokenProvider ->
                    if (done.get()) throw IllegalStateException("Verification expired")
                    tokenProvider.request(StandardIntegrityManager.StandardIntegrityTokenRequest.builder()
                        .setRequestHash(requestHash).build())
                }.addOnSuccessListener { result ->
                    handler.removeCallbacks(timeout)
                    if (done.compareAndSet(false, true)) promise.resolve(Arguments.createMap().apply {
                        putString("locationJson", payload)
                        putString("integrityToken", result.token())
                    })
                }.addOnFailureListener {
                    // Expired providers are prepared on the next user attempt;
                    // never spin on quota/network failures or fall back to Classic.
                    invalidate(provider)
                    handler.removeCallbacks(timeout)
                    if (done.compareAndSet(false, true)) promise.reject("INTEGRITY_FAILED", "No pudimos verificar el dispositivo. Vuelve a intentarlo.")
                }
            }
            override fun onProviderEnabled(provider: String) {}
            override fun onProviderDisabled(provider: String) {
                if (provider == LocationManager.GPS_PROVIDER && !received.get() && done.compareAndSet(false, true)) {
                    manager.removeUpdates(this)
                    handler.removeCallbacks(timeout)
                    promise.reject("LOCATION_DISABLED", "Activa la ubicación del dispositivo.")
                }
            }
            @Deprecated("Legacy callback")
            override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
        }
        handler.post {
            try {
                if (!manager.isProviderEnabled(LocationManager.GPS_PROVIDER)) {
                    if (done.compareAndSet(false, true)) promise.reject("LOCATION_DISABLED", "Activa la ubicación del dispositivo.")
                } else {
                    handler.postDelayed(timeout, 60000)
                    manager.requestLocationUpdates(LocationManager.GPS_PROVIDER, 1000L, 0f, listener, Looper.getMainLooper())
                }
            } catch (_: SecurityException) {
                handler.removeCallbacks(timeout)
                manager.removeUpdates(listener)
                if (done.compareAndSet(false, true)) promise.reject("LOCATION_PERMISSION", "Activa la ubicación precisa para solicitar Bre-B.")
            } catch (_: Exception) {
                handler.removeCallbacks(timeout)
                manager.removeUpdates(listener)
                if (done.compareAndSet(false, true)) promise.reject("LOCATION_FAILED", "No pudimos obtener tu ubicación.")
            }
        }
    }
}
