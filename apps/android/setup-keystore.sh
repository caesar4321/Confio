#!/bin/bash

# Load environment variables
source .env

# Generate keystore
keytool -genkey -v \
  -keystore ../credentials/android/keystore/$KEYSTORE_FILE \
  -alias $KEY_ALIAS \
  -keyalg RSA \
  -keysize 2048 \
  -validity 10000 \
  -storepass $KEYSTORE_PASSWORD \
  -keypass $KEY_PASSWORD \
  -dname "CN=Confio, OU=Confio, O=Confio, L=Caracas, ST=Distrito Capital, C=VE"

# Move keystore to app directory
cp ../credentials/android/keystore/$KEYSTORE_FILE app/

# Verify keystore
keytool -list -v \
  -keystore app/$KEYSTORE_FILE \
  -storepass $KEYSTORE_PASSWORD 