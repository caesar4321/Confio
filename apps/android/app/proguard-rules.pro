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

# Firebase, Google Play Services, AndroidX and OkHttp ship consumer rules.
# Let those rules protect reflective entry points instead of keeping entire
# packages: blanket keeps prevent R8 from shrinking and obfuscating libraries.

# React Native Vision Camera
-keep class com.mrousavy.camera.** { *; }

# Hermés
-keep class com.facebook.hermes.unicode.** { *; }
-keep class com.facebook.jni.** { *; }

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

# Didit SDK
-keep class me.didit.** { *; }
-dontwarn me.didit.**

# Didit React Native bridge
-keep class com.sdkreactnative.** { *; }

# Didit enumerates ReactModuleInfo constructors and invokes them with booleans.
# Preserve their signatures: R8 can otherwise replace a boolean parameter with
# an int, causing an IllegalArgumentException while creating the React context.
-keepclassmembers class com.facebook.react.module.model.ReactModuleInfo {
    public <init>(...);
}

# Preserve metadata used by reflective/generic parsing in release builds
-keepattributes Signature
-keepattributes *Annotation*
-keep class kotlin.Metadata { *; }

# Coroutines used by Didit SDK state observation
-keep class kotlinx.coroutines.** { *; }
-dontwarn kotlinx.coroutines.**
