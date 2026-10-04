// Routes Confío IA voice calls to the loudspeaker. WebRTC's voice-chat audio
// session defaults to the earpiece; an assistant you talk to on screen
// should be heard without holding the phone to your ear.
import AVFoundation
import Foundation
import React
import UIKit

@objc(ConfioAudioRoute)
class ConfioAudioRoute: NSObject {
  @objc static func requiresMainQueueSetup() -> Bool { false }

  /// A light tap when hold-to-talk starts recording.
  @objc(impact)
  func impact() {
    DispatchQueue.main.async {
      let generator = UIImpactFeedbackGenerator(style: .medium)
      generator.prepare()
      generator.impactOccurred()
    }
  }

  @objc(setSpeaker:resolver:rejecter:)
  func setSpeaker(_ on: Bool, resolver resolve: @escaping RCTPromiseResolveBlock,
                  rejecter reject: @escaping RCTPromiseRejectBlock) {
    let session = AVAudioSession.sharedInstance()
    do {
      try session.overrideOutputAudioPort(on ? .speaker : .none)
      resolve(true)
    } catch {
      reject("AUDIO_ROUTE", "No pudimos cambiar el audio.", error)
    }
  }
}
