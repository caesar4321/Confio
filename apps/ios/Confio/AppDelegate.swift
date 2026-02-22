import UIKit
import React
import GoogleSignIn
import FirebaseCore
import FirebaseAppCheck
import Firebase // Force import main module for static linking coverage

@main
class AppDelegate: UIResponder, UIApplicationDelegate, RCTBridgeDelegate {
  var window: UIWindow?

  func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    // Configure App Check BEFORE FirebaseApp.configure()
    #if DEBUG
      // Set a static App Check debug token to avoid registering a new one in Firebase Console on every reinstall
      setenv("FIRAAppCheckDebugToken", "8DB1A0DF-B3C2-4E9D-A480-281CBEB933E1", 1)
      // Use Debug provider for development builds
      let providerFactory = AppCheckDebugProviderFactory()
    #else
      #if targetEnvironment(simulator)
        let providerFactory = AppCheckDebugProviderFactory()
      #else
        // Use custom factory to instantiate AppAttestProvider directly
        let providerFactory = ConfioAppCheckProviderFactory()
      #endif
    #endif
    AppCheck.setAppCheckProviderFactory(providerFactory)
    
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
