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
import androidx.core.content.ContextCompat
import androidx.core.location.LocationManagerCompat
import com.facebook.react.ReactPackage
import com.facebook.react.bridge.*
import com.facebook.react.uimanager.ViewManager
import java.util.concurrent.atomic.AtomicBoolean

class ConfioLocationPackage : ReactPackage {
    override fun createNativeModules(context: ReactApplicationContext): List<NativeModule> = listOf(ConfioLocationModule(context))
    override fun createViewManagers(context: ReactApplicationContext): List<ViewManager<*, *>> = emptyList()
}

/**
 * One position fix for Comprar (city and delivery pin), on the pattern that
 * works for Bre-B: the platform LocationManager directly, a "location is off"
 * answer of its own, and a real wait for a usable fix.
 *
 * Why not getCurrentPosition: with approximate permission Android throttles the
 * network provider to one update per 10 minutes, so a 15 s single request on
 * it never answers (dumpsys showed every request ending empty at 15 s) while
 * the phone already held a fix seconds old. So: the freshest acceptable fix any
 * permitted provider already has, else updates from every enabled permitted
 * provider until one is good enough or the deadline passes.
 */
class ConfioLocationModule(private val context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
    override fun getName() = "ConfioLocation"

    private fun granted(permission: String) =
        ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED

    private fun ageMs(location: Location) =
        (SystemClock.elapsedRealtimeNanos() - location.elapsedRealtimeNanos) / 1_000_000

    private fun usable(location: Location?, maxAgeMs: Long, maxAccuracyM: Double): Boolean {
        if (location == null || !location.latitude.isFinite() || !location.longitude.isFinite()) return false
        val age = ageMs(location)
        if (age < 0 || age > maxAgeMs) return false
        return maxAccuracyM <= 0 || (location.hasAccuracy() && location.accuracy > 0 && location.accuracy <= maxAccuracyM)
    }

    private fun toMap(location: Location): WritableMap = Arguments.createMap().apply {
        putDouble("latitude", location.latitude)
        putDouble("longitude", location.longitude)
        if (location.hasAccuracy()) putDouble("accuracy", location.accuracy.toDouble()) else putNull("accuracy")
        putDouble("ageMs", ageMs(location).toDouble())
        putString("provider", location.provider ?: "")
        putBoolean("mocked", if (Build.VERSION.SDK_INT >= 31) location.isMock else location.isFromMockProvider)
    }

    /**
     * options: precise (needs fine permission and GPS), maxAgeMs, maxAccuracyM
     * (0 = any), timeoutMs. Rejects LOCATION_PERMISSION, LOCATION_DISABLED,
     * LOCATION_TIMEOUT or LOCATION_FAILED.
     */
    @ReactMethod
    fun currentPosition(options: ReadableMap, promise: Promise) {
        val precise = options.hasKey("precise") && options.getBoolean("precise")
        val maxAgeMs = if (options.hasKey("maxAgeMs")) options.getDouble("maxAgeMs").toLong() else 120_000L
        val maxAccuracyM = if (options.hasKey("maxAccuracyM")) options.getDouble("maxAccuracyM") else 0.0
        val timeoutMs = if (options.hasKey("timeoutMs")) options.getDouble("timeoutMs").toLong() else 30_000L

        val fine = granted(Manifest.permission.ACCESS_FINE_LOCATION)
        val coarse = fine || granted(Manifest.permission.ACCESS_COARSE_LOCATION)
        if ((precise && !fine) || !coarse) {
            promise.reject("LOCATION_PERMISSION", if (precise) "Permite la ubicación precisa." else "Permite la ubicación.")
            return
        }
        val manager = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager
        if (!LocationManagerCompat.isLocationEnabled(manager)) {
            promise.reject("LOCATION_DISABLED", "Activa la ubicación del teléfono.")
            return
        }
        // GPS needs fine; the network and passive providers work with either.
        val providers = buildList {
            if (fine) add(LocationManager.GPS_PROVIDER)
            add(LocationManager.NETWORK_PROVIDER)
            if (Build.VERSION.SDK_INT >= 31) add(LocationManager.FUSED_PROVIDER)
            // Passive needed fine permission before Android 8.
            if (fine || Build.VERSION.SDK_INT >= 26) add(LocationManager.PASSIVE_PROVIDER)
        }.filter { name ->
            try { manager.allProviders.contains(name) && (name == LocationManager.PASSIVE_PROVIDER || manager.isProviderEnabled(name)) }
            catch (_: Exception) { false }
        }

        // 1. A fix the phone already has (another app, or a moment ago).
        val cached = providers.mapNotNull { name ->
            try { manager.getLastKnownLocation(name) } catch (_: SecurityException) { null }
        }.filter { usable(it, maxAgeMs, maxAccuracyM) }.minByOrNull { ageMs(it) }
        if (cached != null) {
            promise.resolve(toMap(cached))
            return
        }

        // 2. Ask every enabled provider and take the first good fix.
        val handler = Handler(Looper.getMainLooper())
        val done = AtomicBoolean(false)
        var best: Location? = null
        lateinit var listener: LocationListener
        val finish = { result: Location?, code: String?, message: String? ->
            if (done.compareAndSet(false, true)) {
                try { manager.removeUpdates(listener) } catch (_: Exception) {}
                if (result != null) promise.resolve(toMap(result)) else promise.reject(code ?: "LOCATION_FAILED", message)
            }
        }
        val timeout = Runnable {
            // Out of time: a city lookup takes the best fix seen (approximate is
            // enough); a delivery pin needs the accuracy it asked for.
            val fallback = best
            if (!precise && fallback != null) finish(fallback, null, null)
            else finish(null, "LOCATION_TIMEOUT", "No pudimos obtener tu ubicación.")
        }
        listener = object : LocationListener {
            override fun onLocationChanged(location: Location) {
                if (done.get()) return
                if (usable(location, maxAgeMs, maxAccuracyM)) {
                    handler.removeCallbacks(timeout)
                    finish(location, null, null)
                    return
                }
                // GPS often starts coarse: keep the best so far and keep waiting.
                if (usable(location, maxAgeMs, 0.0)) {
                    val current = best
                    if (current == null || (location.hasAccuracy() && (!current.hasAccuracy() || location.accuracy < current.accuracy))) {
                        best = location
                    }
                }
            }
            override fun onProviderEnabled(provider: String) {}
            override fun onProviderDisabled(provider: String) {
                if (!LocationManagerCompat.isLocationEnabled(manager)) {
                    handler.removeCallbacks(timeout)
                    finish(null, "LOCATION_DISABLED", "Activa la ubicación del teléfono.")
                }
            }
            @Deprecated("Legacy callback")
            override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
        }
        handler.post {
            handler.postDelayed(timeout, timeoutMs)
            // Each provider on its own: one refusing (a permission it needs on
            // this Android version, a provider gone) never cancels the others.
            // Passive rides along on fixes other apps trigger, at no cost.
            var registered = 0
            var refused = false
            providers.forEach { name ->
                try {
                    val interval = if (name == LocationManager.PASSIVE_PROVIDER) 0L else 1000L
                    manager.requestLocationUpdates(name, interval, 0f, listener, Looper.getMainLooper())
                    registered += 1
                } catch (_: SecurityException) {
                    refused = true
                } catch (_: Exception) {
                }
            }
            if (registered == 0) {
                handler.removeCallbacks(timeout)
                if (refused) finish(null, "LOCATION_PERMISSION", "Permite la ubicación.")
                else finish(null, "LOCATION_FAILED", "No pudimos obtener tu ubicación.")
            }
        }
    }
}
