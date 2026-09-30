# Vendored amplify-ui-swift-liveness 1.4.4

Upstream: https://github.com/aws-amplify/amplify-ui-swift-liveness @ 1.4.4
(2ae8ad657ac668484843acd4f7e7a812f76f240e). Tests/HostApp/tooling removed.

Confío patches (search the sources for "Confío patch"):

1. `RecordingButton`: emerald dot instead of the red recording light; its
   label is "VERIFICANDO" via apps/ios/Confio/Localizable.strings.
2. `LivenessViewController.displaySingleFrame`:
upstream adds the frozen last frame *above* the oval mask once the light
challenge ends, so users saw a full-frame photo while the session finished.
The frame is inserted *below* the oval mask so the circle stays until done.
3. `LivenessViewController.showPlaceholderOval`: upstream shows the raw
   full-frame camera until the session's oval arrives (~1s). A centered
   placeholder oval mask covers it from the first frame and is swapped for
   the real oval in `drawOvalInCanvas`.

To upgrade: copy the new upstream tag here, re-apply all patches, drop the
test target from Package.swift.
