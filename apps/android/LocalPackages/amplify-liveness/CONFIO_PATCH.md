# Vendored Amplify UI Android Liveness 1.5.0

Upstream: https://github.com/aws-amplify/amplify-ui-android @ release_liveness_v1.5.0,
`liveness/src/main` only. `build.gradle` replaces upstream's convention plugins
with the same dependencies/versions as the published
`com.amplifyframework.ui:liveness:1.5.0` POM; `LIVENESS_VERSION_NAME` stays
"1.5.0" (reported to AWS with each session). `consumer-rules.pro` is upstream's
`configuration/consumer-rules.pro`.

Confío patches (search the sources for "Confío patch"), matching the iOS
vendored package (apps/ios/LocalPackages/amplify-ui-swift-liveness):

1. `ui/FaceLivenessDetector.kt`: the camera is always masked by an oval.
   Upstream shows the raw camera until the session's oval arrives (~1s) and
   again after the challenge clears it ("Verificando"). Before: the start
   view's standard guide `RectF(120f, 126f, 360f, 514f)`; after: the last oval
   (`LivenessCheckState.Success.faceGuideRect`).
2. `ui/RecordingIndicator.kt`: emerald dot instead of the red recording light;
   the label is "VERIFICANDO" via app/src/main/res/values/face_liveness_strings.xml.

Build changes backported from upstream 6abe43e ("16kb Page Support for
Liveness", in 1.5.1+): CMake `-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON`, and
LiteRT 1.4.0 instead of TensorFlow Lite 2.0.0 / support 0.3.0 (Google Play
rejects native libraries that are not 16 KB-aligned).

To upgrade: copy the new tag's `liveness/src/main`, re-apply both patches,
update versions in build.gradle from its published POM.
