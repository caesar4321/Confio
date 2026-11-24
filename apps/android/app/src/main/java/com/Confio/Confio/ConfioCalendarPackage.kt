package com.Confio.Confio

import android.Manifest
import android.content.ContentUris
import android.content.pm.PackageManager
import android.provider.CalendarContract.Calendars
import android.provider.CalendarContract.Events
import android.provider.CalendarContract.Instances
import android.provider.CalendarContract.Attendees
import com.facebook.react.ReactPackage
import com.facebook.react.bridge.*
import com.facebook.react.uimanager.ViewManager
import java.security.MessageDigest
import java.util.Calendar
import java.util.TimeZone

// Read-only Calendar Provider for Confío IA (docs/designs/assistant-mail-calendar.md).
class ConfioCalendarPackage : ReactPackage {
    override fun createNativeModules(context: ReactApplicationContext): List<NativeModule> = listOf(ConfioCalendarModule(context))
    override fun createViewManagers(context: ReactApplicationContext): List<ViewManager<*, *>> = emptyList()
}

class ConfioCalendarModule(private val context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
    override fun getName() = "ConfioCalendar"

    private fun granted() =
        context.checkSelfPermission(Manifest.permission.READ_CALENDAR) == PackageManager.PERMISSION_GRANTED

    @ReactMethod
    fun permissionStatus(promise: Promise) {
        promise.resolve(if (granted()) "granted" else "denied")
    }

    private data class Source(val rowId: Long, val id: String, val title: String, val account: String, val owner: String)

    // A row id alone is reused once its account is removed, so consent is bound to the account too.
    private fun sources(): List<Source> {
        val found = mutableListOf<Source>()
        val columns = arrayOf(
            Calendars._ID, Calendars.CALENDAR_DISPLAY_NAME, Calendars.ACCOUNT_NAME, Calendars.ACCOUNT_TYPE,
            Calendars.OWNER_ACCOUNT,
        )
        context.contentResolver.query(Calendars.CONTENT_URI, columns, "${Calendars.VISIBLE} = 1", null, null)?.use {
            while (it.moveToNext()) {
                val account = it.getString(2) ?: ""
                val owner = it.getString(4) ?: ""
                val id = digest("${it.getLong(0)}|${it.getString(3) ?: ""}|$account|$owner")
                found.add(Source(it.getLong(0), id, it.getString(1) ?: "", account, owner))
            }
        }
        return found
    }

    @ReactMethod
    fun listCalendars(promise: Promise) {
        if (!granted()) {
            promise.reject("CALENDAR_PERMISSION", "Calendar access is not granted.")
            return
        }
        try {
            val result = Arguments.createArray()
            sources().forEach { source ->
                result.pushMap(Arguments.createMap().apply {
                    putString("id", source.id)
                    putString("title", source.title)
                    putString("account", source.account)
                })
            }
            promise.resolve(result)
        } catch (e: Exception) {
            promise.reject("CALENDAR_READ", "Could not read calendars.")
        }
    }

    @ReactMethod
    fun listEvents(calendarIds: ReadableArray, from: Double, until: Double, promise: Promise) {
        if (!granted()) {
            promise.reject("CALENDAR_PERMISSION", "Calendar access is not granted.")
            return
        }
        if (until <= from || until - from > MAX_WINDOW_MS) {
            promise.reject("CALENDAR_WINDOW", "Invalid window.")
            return
        }
        try {
            val result = Arguments.createArray()
            val wanted = (0 until calendarIds.size()).mapNotNull { calendarIds.getString(it) }.toSet()
            val chosen = sources().filter { it.id in wanted }.associateBy { it.rowId }
            // No chosen calendar means no events, never all of them.
            if (chosen.isEmpty()) {
                promise.resolve(result)
                return
            }
            val uri = Instances.CONTENT_URI.buildUpon().let {
                ContentUris.appendId(it, from.toLong())
                ContentUris.appendId(it, until.toLong())
                it.build()
            }
            val columns = arrayOf(
                Instances.EVENT_ID, Instances.BEGIN, Instances.TITLE, Instances.ALL_DAY, Instances.CALENDAR_ID,
                Events.SELF_ATTENDEE_STATUS, Events.ORGANIZER,
            )
            val selection = "${Instances.CALENDAR_ID} IN (${chosen.keys.joinToString(",")})" +
                " AND (${Events.STATUS} IS NULL OR ${Events.STATUS} != ${Events.STATUS_CANCELED})"
            context.contentResolver.query(uri, columns, selection, null, "${Instances.BEGIN} ASC")?.use {
                while (it.moveToNext() && result.size() < MAX_EVENTS) {
                    val source = chosen[it.getLong(4)] ?: continue
                    if (!accepted(it.getInt(5), it.getString(6), source.owner)) continue
                    val allDay = it.getInt(3) == 1
                    val begin = it.getLong(1)
                    val startsAt = if (allDay) localMidnight(begin) else begin
                    result.pushMap(Arguments.createMap().apply {
                        putString("id", digest("${source.id}|${it.getLong(0)}|$begin"))
                        putString("title", (it.getString(2) ?: "").take(MAX_TITLE))
                        putDouble("startsAt", startsAt.toDouble())
                        putBoolean("allDay", allDay)
                    })
                }
            }
            promise.resolve(result)
        } catch (e: Exception) {
            promise.reject("CALENDAR_READ", "Could not read events.")
        }
    }

    // An invitation the person hasn't answered is someone else's text. The provider keeps
    // status NONE when it was sent to an alias or group, so there the organizer decides.
    private fun accepted(status: Int, organizer: String?, owner: String): Boolean = when (status) {
        Attendees.ATTENDEE_STATUS_ACCEPTED, Attendees.ATTENDEE_STATUS_TENTATIVE -> true
        Attendees.ATTENDEE_STATUS_NONE -> organizer.isNullOrBlank() || organizer.equals(owner, ignoreCase = true)
        else -> false
    }

    private fun digest(value: String): String = MessageDigest.getInstance("SHA-256")
        .digest(value.toByteArray()).take(16).joinToString("") { "%02x".format(it) }

    // All-day events are stored at UTC midnight; west of Greenwich that is the day before.
    private fun localMidnight(utcMidnight: Long): Long {
        val utc = Calendar.getInstance(TimeZone.getTimeZone("UTC")).apply { timeInMillis = utcMidnight }
        return Calendar.getInstance().apply {
            clear()
            set(utc.get(Calendar.YEAR), utc.get(Calendar.MONTH), utc.get(Calendar.DAY_OF_MONTH))
        }.timeInMillis
    }

    private companion object {
        const val MAX_EVENTS = 200
        const val MAX_TITLE = 300
        const val MAX_WINDOW_MS = 31.0 * 86_400_000
    }
}
