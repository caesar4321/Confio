cmake_minimum_required(VERSION 3.13)

# Define the project name
project(Confio)

# Set C++ standard
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find required packages
find_package(ReactAndroid REQUIRED CONFIG)
find_package(fbjni REQUIRED CONFIG)

# Set the path to react-native-worklets-core
set(RNWORKLETS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../../node_modules/react-native-worklets-core/android")

# Add react-native-worklets-core
find_package(rnworklets REQUIRED CONFIG 
    PATHS ${RNWORKLETS_DIR}
    NO_DEFAULT_PATH
)

# Add worklets library
add_library(worklets SHARED IMPORTED)
set_target_properties(worklets PROPERTIES IMPORTED_LOCATION
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../node_modules/react-native-worklets-core/android/build/intermediates/cxx/Debug/1n6dm612/obj/${ANDROID_ABI}/libworklets.so)

# Add VisionCamera library
add_library(VisionCamera SHARED
    VisionCamera.cpp
    MutableJByteBuffer.cpp
    frameprocessors/FrameHostObject.cpp
    frameprocessors/FrameProcessorPluginHostObject.cpp
    frameprocessors/JSIJNIConversion.cpp
    frameprocessors/VisionCameraProxy.cpp
    frameprocessors/java-bindings/JSharedArray.cpp
    frameprocessors/java-bindings/JFrame.cpp
    frameprocessors/java-bindings/JFrameProcessor.cpp
    frameprocessors/java-bindings/JFrameProcessorPlugin.cpp
    frameprocessors/java-bindings/JVisionCameraProxy.cpp
    frameprocessors/java-bindings/JVisionCameraScheduler.cpp
)

# Link libraries
target_link_libraries(VisionCamera
    ReactAndroid::jsi
    fbjni::fbjni
    worklets
    android
    log
)

# Include directories
target_include_directories(VisionCamera PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../node_modules/react-native-worklets-core/android/build/headers/rnworklets
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../node_modules/react-native/ReactCommon/jsi
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../node_modules/react-native/ReactAndroid/src/main/jni/react/jni
)

# Add your source files
add_library(confio SHARED
    confio.cpp
)

# Link against required libraries
target_link_libraries(confio
    ReactAndroid::jsi
    rnworklets::rnworklets
)