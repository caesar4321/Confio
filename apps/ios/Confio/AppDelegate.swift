import UIKit
import React
import GoogleSignIn
import FirebaseCore
import FirebaseAppCheck
import Firebase // Force import main module for static linking coverage

@main
class AppDelegate: UIResponder, UIApplicationDelegate, RCTBridgeDelegate {
  var window: UIWindow?

  private func shouldUseDebugAppCheck() -> Bool {
    #if DEBUG
      return true
    #else
      if ProcessInfo.processInfo.environment["CONFIO_FORCE_DEBUG_APP_CHECK"] == "1" {
        return true
      }

      // Xcode/device-development installs include an embedded provisioning profile.
      // App Store and TestFlight distributions do not, so they can use real attestation.
      if Bundle.main.path(forResource: "embedded", ofType: "mobileprovision") != nil {
        return true
      }

      return false
    #endif
  }

  func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    let useDebugAppCheck = shouldUseDebugAppCheck()
    // Configure App Check BEFORE FirebaseApp.configure()
    if useDebugAppCheck {
      // Set a static App Check debug token to avoid registering a new one in Firebase Console on every reinstall
      setenv("FIRAAppCheckDebugToken", "A2600262-DC63-4467-93A0-5840608F8738", 1)
      // Use Debug provider for development-signed local builds.
      let providerFactory = AppCheckDebugProviderFactory()
      AppCheck.setAppCheckProviderFactory(providerFactory)
    } else {
      #if targetEnvironment(simulator)
        let providerFactory = AppCheckDebugProviderFactory()
      #else
        // Use custom factory to instantiate AppAttestProvider directly
        let providerFactory = ConfioAppCheckProviderFactory()
      #endif
      AppCheck.setAppCheckProviderFactory(providerFactory)
    }
    
    // Initialize Firebase
    FirebaseApp.configure()
    
    // unwrap the optional bridge
    guard let bridge = RCTBridge(delegate: self, launchOptions: launchOptions) else {
      fatalError("Failed to create RCTBridge")
    }
    let rootView = RCTRootView(
      bridge: bridge,
      moduleName: "Confio",
      initialProperties: nil
    )
    
    if #available(iOS 13.0, *) {
      rootView.backgroundColor = .systemBackground
    } else {
      rootView.backgroundColor = .white
    }
    
    window = UIWindow(frame: UIScreen.main.bounds)
    let rootVC = UIViewController()
    rootVC.view = rootView
    window?.rootViewController = rootVC
    window?.makeKeyAndVisible()
    
    return true
  }

  // new signature: bridge is implicitly unwrapped
  func sourceURL(for bridge: RCTBridge!) -> URL! {
    #if DEBUG
      // .sharedSettings() is non-optional, and fallbackExtension takes the file extension
      return RCTBundleURLProvider
               .sharedSettings()
               .jsBundleURL(forBundleRoot: "index", fallbackExtension: "js")
    #else
      return Bundle.main.url(forResource: "main", withExtension: "jsbundle")
    #endif
  }

  func application(_ app: UIApplication,
                  open url: URL,
                  options: [UIApplication.OpenURLOptionsKey : Any] = [:]) -> Bool {
    if GIDSignIn.sharedInstance.handle(url) {
      return true
    }


    return RCTLinkingManager.application(app, open: url, options: options)
  }

  func application(_ application: UIApplication, continue userActivity: NSUserActivity, restorationHandler: @escaping ([UIUserActivityRestoring]?) -> Void) -> Bool {
    return RCTLinkingManager.application(application, continue: userActivity, restorationHandler: restorationHandler)
  }
}

// Custom Provider Factory to handle App Attest availability
class ConfioAppCheckProviderFactory: NSObject, AppCheckProviderFactory {
  func createProvider(with app: FirebaseApp) -> AppCheckProvider? {
    if #available(iOS 14.0, *) {
      // Use App Attest on iOS 14+
      return AppAttestProvider(app: app)
    } else {
      // Fallback to DeviceCheck on iOS < 14
      return DeviceCheckProvider(app: app)
    }
  }
}
