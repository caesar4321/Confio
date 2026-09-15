import Foundation
import CoreLocation
import DeviceCheck
import CryptoKit
import React

@objc(BrebAppleLocation)
class BrebAppleLocation: NSObject, CLLocationManagerDelegate {
  private let manager = CLLocationManager()
  private let keyName = "confio.breb.appattest.key.v1"
  private var resolve: RCTPromiseResolveBlock?
  private var reject: RCTPromiseRejectBlock?
  private var timeout: DispatchWorkItem?
  private var operation = UUID()
  private var challenge = ""
  private var registered = false
  private var received = false
  private var permissionResolve: RCTPromiseResolveBlock?
  @objc static func requiresMainQueueSetup() -> Bool { true }

  /// Asks for location first, before any key, server or attestation step, and
  /// answers once the person has decided: granted | reduced | denied | undetermined.
  @objc func requestPermission(_ resolve: @escaping RCTPromiseResolveBlock, rejecter reject: @escaping RCTPromiseRejectBlock) {
    DispatchQueue.main.async {
      self.manager.delegate = self
      if self.manager.authorizationStatus == .notDetermined {
        self.permissionResolve = resolve
        self.manager.requestWhenInUseAuthorization()
      } else {
        self.resolvePrecision(resolve)
      }
    }
  }
  private func permissionState() -> String {
    switch manager.authorizationStatus {
    case .authorizedAlways, .authorizedWhenInUse:
      if #available(iOS 14.0, *), manager.accuracyAuthorization != .fullAccuracy { return "reduced" }
      return "granted"
    case .notDetermined: return "undetermined"
    default: return "denied"
    }
  }
  /// Bre-B needs a precise reading: when only an approximate one was shared,
  /// ask once for full accuracy for this purpose (Info.plist "BrebLocation").
  private func resolvePrecision(_ resolve: @escaping RCTPromiseResolveBlock) {
    if #available(iOS 14.0, *), permissionState() == "reduced" {
      manager.requestTemporaryFullAccuracyAuthorization(withPurposeKey: "BrebLocation") { _ in
        DispatchQueue.main.async { resolve(self.permissionState()) }
      }
    } else {
      resolve(permissionState())
    }
  }

  @objc func keyId(_ resolve: RCTPromiseResolveBlock, rejecter reject: RCTPromiseRejectBlock) {
    resolve(UserDefaults.standard.string(forKey: keyName) ?? "")
  }
  @objc func hasPermission(_ resolve: @escaping RCTPromiseResolveBlock, rejecter reject: @escaping RCTPromiseRejectBlock) {
    DispatchQueue.main.async {
      if #available(iOS 15.0, *) {
        resolve(DCAppAttestService.shared.isSupported &&
          [.authorizedAlways, .authorizedWhenInUse].contains(self.manager.authorizationStatus) &&
          self.manager.accuracyAuthorization == .fullAccuracy)
      } else { resolve(false) }
    }
  }
  @objc func attest(_ challenge: String, registered: Bool, resolver resolve: @escaping RCTPromiseResolveBlock, rejecter reject: @escaping RCTPromiseRejectBlock) {
    DispatchQueue.main.async {
      guard #available(iOS 15.0, *), DCAppAttestService.shared.isSupported else {
        reject("UNSUPPORTED", "Este dispositivo no admite la verificación segura de Bre-B.", nil); return
      }
      guard self.resolve == nil else { reject("BUSY", "Ya estamos verificando tu ubicación.", nil); return }
      self.operation = UUID()
      self.challenge = challenge; self.registered = registered; self.received = false
      self.resolve = resolve; self.reject = reject
      self.manager.delegate = self
      self.manager.desiredAccuracy = kCLLocationAccuracyBest
      let id = self.operation
      let timeout = DispatchWorkItem { if self.operation == id { self.fail("No pudimos verificar tu ubicación. Intenta de nuevo.") } }
      self.timeout = timeout
      DispatchQueue.main.asyncAfter(deadline: .now() + 90, execute: timeout)
      if self.manager.authorizationStatus == .notDetermined { self.manager.requestWhenInUseAuthorization() }
      else { self.startLocation() }
    }
  }
  private func fail(_ message: String) {
    let callback = reject
    finish()
    callback?("BREB_VERIFICATION", message, nil)
  }
  private func finish() {
    manager.stopUpdatingLocation(); timeout?.cancel(); timeout = nil
    resolve = nil; reject = nil; operation = UUID()
  }
  private func startLocation() {
    guard resolve != nil, !received else { return }
    if #available(iOS 15.0, *) {
      guard [.authorizedAlways, .authorizedWhenInUse].contains(manager.authorizationStatus),
            manager.accuracyAuthorization == .fullAccuracy else {
        fail("Permite la ubicación precisa en Ajustes para usar Bre-B."); return
      }
      manager.requestLocation()
    }
  }
  func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
    if let pending = permissionResolve, manager.authorizationStatus != .notDetermined {
      permissionResolve = nil
      resolvePrecision(pending)
    }
    if #available(iOS 14.0, *), manager.authorizationStatus != .notDetermined { startLocation() }
  }
  func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
    if resolve != nil, !received { fail("No pudimos obtener tu ubicación precisa. Intenta de nuevo.") }
  }
  func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
    guard #available(iOS 15.0, *), resolve != nil, !received, let location = locations.last else { return }
    received = true
    manager.stopUpdatingLocation()
    guard let source = location.sourceInformation, !source.isSimulatedBySoftware, !source.isProducedByAccessory,
          location.horizontalAccuracy > 0, location.horizontalAccuracy <= 100,
          (-5...120).contains(-location.timestamp.timeIntervalSinceNow) else {
      fail("Necesitamos una ubicación precisa y sin simulación."); return
    }
    let payload: [String: Any] = ["latitude": location.coordinate.latitude, "longitude": location.coordinate.longitude,
      "accuracy": location.horizontalAccuracy, "timestamp": location.timestamp.timeIntervalSince1970 * 1000, "mocked": false]
    guard let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]),
          let json = String(data: data, encoding: .utf8) else { fail("No pudimos verificar tu ubicación."); return }
    let hash = Data(SHA256.hash(data: Data((challenge + "." + json).utf8)))
    let id = operation
    let service = DCAppAttestService.shared
    let submit: (String, Bool) -> Void = { key, registration in
      let completion: (Data?, Error?) -> Void = { object, error in
        DispatchQueue.main.async {
          guard self.operation == id, self.resolve != nil else { return }
          guard let object = object, error == nil else {
            if (error as? DCError)?.code == .invalidKey {
              UserDefaults.standard.removeObject(forKey: self.keyName)
            }
            self.fail("No pudimos verificar el dispositivo. Intenta más tarde."); return
          }
          if registration { UserDefaults.standard.set(key, forKey: self.keyName) }
          let envelope = ["mode": registration ? "attestation" : "assertion", "keyId": key, "object": object.base64EncodedString()]
          guard let encoded = try? JSONSerialization.data(withJSONObject: envelope),
                let token = String(data: encoded, encoding: .utf8) else { self.fail("No pudimos verificar el dispositivo."); return }
          let callback = self.resolve
          self.finish()
          callback?(["locationJson": json, "integrityToken": token])
        }
      }
      if registration { service.attestKey(key, clientDataHash: hash, completionHandler: completion) }
      else { service.generateAssertion(key, clientDataHash: hash, completionHandler: completion) }
    }
    if registered, let key = UserDefaults.standard.string(forKey: keyName) { submit(key, false) }
    else {
      // Unregistered keys are never re-attested with a different challenge.
      // Rotate after a lost/failed registration; a successful lost response
      // is discovered by the next server challenge's keyRegistered field.
      service.generateKey { key, error in
        DispatchQueue.main.async {
          guard self.operation == id else { return }
          guard let key = key, error == nil else { self.fail("No pudimos preparar el dispositivo."); return }
          submit(key, true)
        }
      }
    }
  }
}
