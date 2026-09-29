import AWSPluginsCore
import FaceLiveness
import Foundation
import React
import SwiftUI
import UIKit

/// Runs one AWS Rekognition Face Liveness capture for the face step-up.
/// The session and the short-lived, single-action credentials come from the
/// Confío backend (startFaceCheck); grading happens server-side
/// (completeFaceCheck), so this only reports whether the capture finished.
@objc(ConfioFaceLiveness)
final class ConfioFaceLiveness: NSObject {
  private var resolve: RCTPromiseResolveBlock?
  private var reject: RCTPromiseRejectBlock?
  private weak var host: UIViewController?

  @objc static func requiresMainQueueSetup() -> Bool { true }

  @objc(start:region:credentials:resolver:rejecter:)
  func start(
    _ sessionId: String,
    region: String,
    credentials: NSDictionary,
    resolver resolve: @escaping RCTPromiseResolveBlock,
    rejecter reject: @escaping RCTPromiseRejectBlock
  ) {
    DispatchQueue.main.async {
      guard self.resolve == nil else {
        reject("busy", "A face check is already running", nil)
        return
      }
      guard
        let accessKeyId = credentials["accessKeyId"] as? String,
        let secretAccessKey = credentials["secretAccessKey"] as? String,
        let sessionToken = credentials["sessionToken"] as? String,
        let expiration = credentials["expirationEpochSeconds"] as? Double
      else {
        reject("bad_arguments", "Missing credentials", nil)
        return
      }
      guard let presenter = RCTPresentedViewController() else {
        reject("no_activity", "No active screen", nil)
        return
      }
      self.resolve = resolve
      self.reject = reject
      let provider = StaticCredentialsProvider(credentials: TemporaryCredentials(
        accessKeyId: accessKeyId,
        secretAccessKey: secretAccessKey,
        sessionToken: sessionToken,
        expiration: Date(timeIntervalSince1970: expiration)
      ))
      let view = LivenessHostView(sessionId: sessionId, region: region, provider: provider) { [weak self] result in
        self?.finish(result)
      }
      let controller = UIHostingController(rootView: view)
      controller.modalPresentationStyle = .fullScreen
      controller.isModalInPresentation = true
      self.host = controller
      presenter.present(controller, animated: true)
    }
  }

  private func finish(_ result: Result<Void, FaceLivenessDetectionError>) {
    DispatchQueue.main.async {
      let resolve = self.resolve
      let reject = self.reject
      self.resolve = nil
      self.reject = nil
      let settle = {
        switch result {
        case .success:
          resolve?("complete")
        case .failure(let error):
          let code = error == .userCancelled ? "UserCancelledException" : String(describing: error)
          reject?(code, code, nil)
        }
      }
      if let host = self.host {
        host.dismiss(animated: true, completion: settle)
      } else {
        settle()
      }
      self.host = nil
    }
  }
}

private struct TemporaryCredentials: AWSTemporaryCredentials {
  let accessKeyId: String
  let secretAccessKey: String
  let sessionToken: String
  let expiration: Date
}

private struct StaticCredentialsProvider: AWSCredentialsProvider {
  let credentials: TemporaryCredentials

  func fetchAWSCredentials() async throws -> AWSCredentials {
    credentials
  }
}

private struct LivenessHostView: View {
  let sessionId: String
  let region: String
  let provider: StaticCredentialsProvider
  let onCompletion: (Result<Void, FaceLivenessDetectionError>) -> Void
  @State private var isPresented = true

  var body: some View {
    FaceLivenessDetectorView(
      sessionID: sessionId,
      credentialsProvider: provider,
      region: region,
      // Confío shows its own intro (including the flashing-light notice).
      disableStartView: true,
      isPresented: $isPresented,
      onCompletion: onCompletion
    )
  }
}
