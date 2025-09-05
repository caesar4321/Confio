package com.Confio.Confio

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import com.facebook.react.bridge.*

class MediaPickerModule(private val reactContext: ReactApplicationContext) :
  ReactContextBaseJavaModule(reactContext), ActivityEventListener {

  private var pendingPromise: Promise? = null
  private var requestCode: Int = 0

  companion object {
    private const val REQ_PICK_IMAGE = 52001
    private const val REQ_PICK_VIDEO = 52002
  }

  override fun getName(): String = "MediaPicker"

  init {
    reactContext.addActivityEventListener(this)
  }

  @ReactMethod
  fun pickImage(promise: Promise) {
    launchPicker("image/*", REQ_PICK_IMAGE, promise)
  }

  @ReactMethod
  fun pickVideo(promise: Promise) {
    launchPicker("video/*", REQ_PICK_VIDEO, promise)
  }

  private fun launchPicker(mimeType: String, code: Int, promise: Promise) {
    val activity: Activity? = currentActivity
    if (activity == null) {
      promise.reject("NO_ACTIVITY", "Current activity is null")
      return
    }

    if (pendingPromise != null) {
      pendingPromise?.reject("IN_PROGRESS", "Another picker is in progress")
      pendingPromise = null
    }

    pendingPromise = promise
    requestCode = code

    try {
      val intent: Intent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        Intent(MediaStore.ACTION_PICK_IMAGES).apply {
          type = mimeType
        }
      } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.KITKAT) {
        Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
          addCategory(Intent.CATEGORY_OPENABLE)
          type = mimeType
          putExtra(Intent.EXTRA_ALLOW_MULTIPLE, false)
        }
      } else {
        Intent(Intent.ACTION_GET_CONTENT).apply {
          addCategory(Intent.CATEGORY_OPENABLE)
          type = mimeType
        }
      }

      intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
      activity.startActivityForResult(intent, code)
    } catch (e: Exception) {
      pendingPromise?.reject("INTENT_ERROR", e.message, e)
      pendingPromise = null
    }
  }

  override fun onActivityResult(activity: Activity?, requestCode: Int, resultCode: Int, data: Intent?) {
    val promise = pendingPromise ?: return
    if (requestCode != this.requestCode) return

    pendingPromise = null

    if (resultCode != Activity.RESULT_OK) {
      // User cancelled; resolve with null to keep flow simple
      promise.resolve(null)
      return
    }

    val uri: Uri? = data?.data
    if (uri == null) {
      promise.resolve(null)
      return
    }

    promise.resolve(uri.toString())
  }

  override fun onNewIntent(intent: Intent?) {
    // no-op
  }
}

