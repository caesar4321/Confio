import UIKit
import React
import GoogleSignIn
import FirebaseCore
import Firebase // Force import main module for static linking coverage

@main
class AppDelegate: UIResponder, UIApplicationDelegate, RCTBridgeDelegate {
  var window: UIWindow?

  func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    // Register RNFirebase's configurable provider BEFORE Firebase creates App Check.
    // JavaScript then selects App Attest or the explicitly enabled debug provider.
    RNFBAppCheckModule.sharedInstance()
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
