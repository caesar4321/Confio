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
  // Created once, by the first scene. A scene iOS rebuilds (after discarding
  // it in the background) reuses both: a new root view would remount the
  // whole app and replay the cold-start link from the bridge's launch options.
  var bridge: RCTBridge?
  var reactRootViewController: UIViewController?

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

// Owns the status bar for React Native's <StatusBar>. Apps linked against the
// iOS 27 SDK can no longer set it through UIApplication, so the patched
// RCTStatusBarManager (patches/react-native+0.79.7.patch) posts each request
// here and UIKit reads it back from this controller.
final class ReactRootViewController: UIViewController {
  private var statusBarStyle: UIStatusBarStyle = .default
  private var statusBarHidden = false
  private var hiddenAnimation: UIStatusBarAnimation = .none

  override init(nibName nibNameOrNil: String?, bundle nibBundleOrNil: Bundle?) {
    super.init(nibName: nibNameOrNil, bundle: nibBundleOrNil)
    NotificationCenter.default.addObserver(self, selector: #selector(applyStatusBarRequest(_:)),
                                           name: Notification.Name("RCTStatusBarAppearanceRequest"),
                                           object: nil)
  }

  required init?(coder: NSCoder) {
    fatalError("init(coder:) is not supported")
  }

  // react-native-screens swizzles UIViewController so the status bar comes
  // from the top RNSScreen, which only knows native-stack options (unused
  // here). <StatusBar> requests land on this controller, so it keeps it.
  override var childForStatusBarStyle: UIViewController? { nil }
  override var childForStatusBarHidden: UIViewController? { nil }
  override var preferredStatusBarStyle: UIStatusBarStyle { statusBarStyle }
  override var prefersStatusBarHidden: Bool { statusBarHidden }
  override var preferredStatusBarUpdateAnimation: UIStatusBarAnimation { hiddenAnimation }

  // Posted on the main queue by RCTStatusBarManager.
  @objc private func applyStatusBarRequest(_ notification: Notification) {
    let info = notification.userInfo ?? [:]
    var animated = false
    if let raw = (info["style"] as? NSNumber)?.intValue, let style = UIStatusBarStyle(rawValue: raw) {
      statusBarStyle = style
      animated = (info["animated"] as? NSNumber)?.boolValue ?? false
    }
    if let hidden = (info["hidden"] as? NSNumber)?.boolValue {
      statusBarHidden = hidden
      let raw = (info["animation"] as? NSNumber)?.intValue ?? 0
      hiddenAnimation = UIStatusBarAnimation(rawValue: raw) ?? .none
      animated = hiddenAnimation != .none
    }
    if animated {
      UIView.animate(withDuration: 0.25) { self.setNeedsStatusBarAppearanceUpdate() }
    } else {
      setNeedsStatusBarAppearanceUpdate()
    }
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

    let rootVC: UIViewController
    let reconnecting: Bool
    if let existing = appDelegate.reactRootViewController {
      rootVC = existing
      reconnecting = true
    } else {
      // Linking.getInitialURL() reads the bridge's launch options, which no
      // longer carry the URL that opened the app: hand it over from the scene.
      guard let bridge = RCTBridge(delegate: appDelegate,
                                   launchOptions: Self.launchOptions(from: connectionOptions,
                                                                     includeURL: !googleHandled)) else {
        fatalError("Failed to create RCTBridge")
      }
      let rootView = RCTRootView(bridge: bridge, moduleName: "Confio", initialProperties: nil)
      rootView.backgroundColor = .systemBackground
      rootVC = ReactRootViewController()
      rootVC.view = rootView
      appDelegate.bridge = bridge
      appDelegate.reactRootViewController = rootVC
      reconnecting = false
    }

    let window = UIWindow(windowScene: windowScene)
    window.rootViewController = rootVC
    self.window = window
    appDelegate.window = window
    window.makeKeyAndVisible()

    if reconnecting {
      // JavaScript is still mounted and listening: deliver the link as a live event.
      if let url = launchURL, !googleHandled {
        _ = RCTLinkingManager.application(UIApplication.shared, open: url, options: [:])
      }
      for activity in connectionOptions.userActivities {
        _ = RCTLinkingManager.application(UIApplication.shared, continue: activity) { _ in }
      }
    }
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
