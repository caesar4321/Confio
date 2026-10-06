import UIKit
import React
import GoogleSignIn
import FirebaseCore
import Firebase // Force import main module for static linking coverage

@main
class AppDelegate: UIResponder, UIApplicationDelegate, RCTBridgeDelegate {
  // Mirrors the scene's window: Reanimated, RNFB Messaging, react-native-share
  // and react-native-contacts still read UIApplication.delegate.window.
  var window: UIWindow?
  // Created once, by the first scene; a reconnected scene reuses it.
  var bridge: RCTBridge?

  func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    // Register RNFirebase's configurable provider BEFORE Firebase creates App Check.
    // JavaScript then selects App Attest or the explicitly enabled debug provider.
    RNFBAppCheckModule.sharedInstance()
    FirebaseApp.configure()

    // The window and the React bridge come from SceneDelegate: apps built with
    // the iOS 27 SDK must adopt the UIScene life cycle or they fail to launch.
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

// Under the scene life cycle, links arrive here instead of the AppDelegate
// methods above: a cold start through `connectionOptions`, a warm one through
// the scene callbacks.
class SceneDelegate: UIResponder, UIWindowSceneDelegate {
  var window: UIWindow?

  func scene(
    _ scene: UIScene,
    willConnectTo session: UISceneSession,
    options connectionOptions: UIScene.ConnectionOptions
  ) {
    guard let windowScene = scene as? UIWindowScene,
          let appDelegate = UIApplication.shared.delegate as? AppDelegate else { return }

    // Google Sign-In's own redirect, if that is what launched the app, is
    // Google's alone; any other URL goes to React Native below.
    let launchURL = connectionOptions.urlContexts.first?.url
    let googleHandled = launchURL.map { GIDSignIn.sharedInstance.handle($0) } ?? false

    let bridge: RCTBridge
    if let existing = appDelegate.bridge {
      bridge = existing
      // JavaScript is already running: deliver the link as a live event.
      if let url = launchURL, !googleHandled {
        _ = RCTLinkingManager.application(UIApplication.shared, open: url, options: [:])
      }
      for activity in connectionOptions.userActivities {
        _ = RCTLinkingManager.application(UIApplication.shared, continue: activity) { _ in }
      }
    } else {
      // Linking.getInitialURL() reads the bridge's launch options, which no
      // longer carry the URL that opened the app: hand it over from the scene.
      guard let created = RCTBridge(delegate: appDelegate,
                                    launchOptions: Self.launchOptions(from: connectionOptions,
                                                                      includeURL: !googleHandled)) else {
        fatalError("Failed to create RCTBridge")
      }
      appDelegate.bridge = created
      bridge = created
    }

    let rootView = RCTRootView(bridge: bridge, moduleName: "Confio", initialProperties: nil)
    rootView.backgroundColor = .systemBackground

    let window = UIWindow(windowScene: windowScene)
    let rootVC = UIViewController()
    rootVC.view = rootView
    window.rootViewController = rootVC
    self.window = window
    appDelegate.window = window
    window.makeKeyAndVisible()
  }

  func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
    for context in URLContexts {
      if GIDSignIn.sharedInstance.handle(context.url) { continue }
      var options: [UIApplication.OpenURLOptionsKey: Any] = [:]
      if let source = context.options.sourceApplication {
        options[.sourceApplication] = source
      }
      _ = RCTLinkingManager.application(UIApplication.shared, open: context.url, options: options)
    }
  }

  func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
    _ = RCTLinkingManager.application(UIApplication.shared, continue: userActivity) { _ in }
  }

  func sceneDidDisconnect(_ scene: UIScene) {
    if (UIApplication.shared.delegate as? AppDelegate)?.window === window {
      (UIApplication.shared.delegate as? AppDelegate)?.window = nil
    }
    window = nil
  }

  // The keys RCTLinkingManager.getInitialURL reads.
  private static func launchOptions(from options: UIScene.ConnectionOptions,
                                    includeURL: Bool) -> [UIApplication.LaunchOptionsKey: Any]? {
    if includeURL, let url = options.urlContexts.first?.url {
      return [.url: url]
    }
    if let activity = options.userActivities.first(where: { $0.activityType == NSUserActivityTypeBrowsingWeb }) {
      return [.userActivityDictionary: [
        UIApplication.LaunchOptionsKey.userActivityType: activity.activityType,
        "UIApplicationLaunchOptionsUserActivityKey": activity,
      ]]
    }
    return nil
  }
}
