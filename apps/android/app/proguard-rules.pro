# React Native Standard Rules
-keep class com.facebook.react.turbomodule.** { *; }
-keep class com.facebook.react.bridge.** { *; }
-keep class com.facebook.react.uimanager.** { *; }
-keep class com.facebook.react.module.annotations.** { *; }

# React Native Reanimated
-keep class com.swmansion.reanimated.** { *; }
-keep class com.facebook.react.turbomodule.** { *; }

# React Native Vector Icons
-keep class com.oblador.vectoricons.** { *; }

# React Native Firebase
-keep class io.invertase.firebase.** { *; }
-keep class com.google.firebase.** { *; }
-dontwarn com.google.firebase.**

# Google Play Services (Auth, Integrity)
-keep class com.google.android.gms.** { *; }
-dontwarn com.google.android.gms.**

# React Native Vision Camera
-keep class com.mrousavy.camera.** { *; }

# OkHttp (Network)
-keepattributes Signature
-keepattributes *Annotation*
-keep class okhttp3.** { *; }
-keep interface okhttp3.** { *; }
-dontwarn okhttp3.**

# Hermés
-keep class com.facebook.hermes.unicode.** { *; }
-keep class com.facebook.jni.** { *; }

# Android X & Support Libraries
-keep class androidx.** { *; }
-keep interface androidx.** { *; }
-dontwarn androidx.**

# React Native Screens
-keep class com.swmansion.rnscreens.** { *; }

# React Native Safe Area Context
-keep class com.th3rdwave.safeareacontext.** { *; }

# React Native Device Info
-keep class com.learnium.RNDeviceInfo.** { *; }

# Keep our own classes (optional, but good for JNI callbacks)
-keep class com.Confio.Confio.** { *; }

# Reflection usage
-keepattributes EnclosingMethod
-keepattributes InnerClasses
-keepattributes Exceptions
