cmake_minimum_required(VERSION 3.13)

# Define the project name
project(Confio)

# Set C++ standard
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find required packages
find_package(ReactAndroid REQUIRED CONFIG)

# Set the path to react-native-worklets-core
set(RNWORKLETS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../../node_modules/react-native-worklets-core/android")

# Add react-native-worklets-core
find_package(rnworklets REQUIRED CONFIG 
    PATHS ${RNWORKLETS_DIR}
    NO_DEFAULT_PATH
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