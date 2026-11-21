import UIKit
import CoreImage
import ImageIO
import UniformTypeIdentifiers

/// "Compartir → Confío" for an image: a store's or app's payment QR, or its
/// screenshot. The QR is read here, on the device, and Confío opens Pagar with
/// it (confio://shared-qr?p=…, handled by useSharedQr). Nothing is paid here:
/// the person reviews the merchant and amount and confirms inside Confío.
final class ShareViewController: UIViewController {
  private var handled = false

  override func viewDidLoad() {
    super.viewDidLoad()
    view.backgroundColor = UIColor.black.withAlphaComponent(0.2)
  }

  override func viewDidAppear(_ animated: Bool) {
    super.viewDidAppear(animated)
    guard !handled else { return }
    handled = true
    loadImage { [weak self] image in
      let payload = image.flatMap(Self.qrPayload)
      DispatchQueue.main.async { self?.finish(with: payload) }
    }
  }

  /// A camera photo decoded at full size can exceed a share extension's
  /// memory limit (~120 MB): read a downsampled copy, plenty for a QR.
  private static func downsampled(_ source: CGImageSource?) -> UIImage? {
    guard let source else { return nil }
    let options: [CFString: Any] = [
      kCGImageSourceCreateThumbnailFromImageAlways: true,
      kCGImageSourceCreateThumbnailWithTransform: true,
      kCGImageSourceShouldCacheImmediately: true,
      kCGImageSourceThumbnailMaxPixelSize: 2048,
    ]
    return CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary).map(UIImage.init(cgImage:))
  }

  private func loadImage(_ done: @escaping (UIImage?) -> Void) {
    let providers = (extensionContext?.inputItems as? [NSExtensionItem] ?? [])
      .flatMap { $0.attachments ?? [] }
    let type = UTType.image.identifier
    guard let provider = providers.first(where: { $0.hasItemConformingToTypeIdentifier(type) }) else {
      done(nil)
      return
    }
    provider.loadItem(forTypeIdentifier: type, options: nil) { item, _ in
      switch item {
      case let url as URL: done(Self.downsampled(CGImageSourceCreateWithURL(url as CFURL, nil)))
      case let data as Data: done(Self.downsampled(CGImageSourceCreateWithData(data as CFData, nil)))
      case let image as UIImage:
        done(image.pngData().flatMap { Self.downsampled(CGImageSourceCreateWithData($0 as CFData, nil)) } ?? image)
      default: done(nil)
      }
    }
  }

  /// The first QR code in the image, read with Core Image (no network).
  private static func qrPayload(_ image: UIImage) -> String? {
    guard let ciImage = image.ciImage ?? image.cgImage.map({ CIImage(cgImage: $0) }),
          let detector = CIDetector(ofType: CIDetectorTypeQRCode, context: nil,
                                    options: [CIDetectorAccuracy: CIDetectorAccuracyHigh]) else { return nil }
    let payload = detector.features(in: ciImage)
      .compactMap { ($0 as? CIQRCodeFeature)?.messageString }
      .first { !$0.isEmpty }
    guard let payload, payload.count <= 4096 else { return nil }
    return payload
  }

  private func finish(with payload: String?) {
    // ASCII-only escaping: a merchant city like "SÃO PAULO" must not make
    // the link invalid (URL(string:) rejects raw non-ASCII before iOS 17).
    let unreserved = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
    guard let payload,
          let encoded = payload.addingPercentEncoding(withAllowedCharacters: unreserved),
          let url = URL(string: "confio://shared-qr?p=\(encoded)") else {
      let alert = UIAlertController(title: "Sin código QR",
                                    message: "No encontramos un código QR en esta imagen.",
                                    preferredStyle: .alert)
      alert.addAction(UIAlertAction(title: "Entendido", style: .default) { [weak self] _ in
        self?.extensionContext?.completeRequest(returningItems: nil)
      })
      present(alert, animated: true)
      return
    }
    openContainingApp(url)
    extensionContext?.completeRequest(returningItems: nil)
  }

  /// Share extensions cannot call UIApplication.open directly; the running
  /// application object is reached through the responder chain.
  private func openContainingApp(_ url: URL) {
    let selector = sel_registerName("openURL:options:completionHandler:")
    var responder: UIResponder? = self
    while let current = responder {
      if let application = current as? UIApplication, application.responds(to: selector) {
        typealias Open = @convention(c) (NSObject, Selector, NSURL, NSDictionary, Any?) -> Void
        let open = unsafeBitCast(application.method(for: selector), to: Open.self)
        open(application, selector, url as NSURL, NSDictionary(), nil)
        return
      }
      responder = current.next
    }
  }
}
