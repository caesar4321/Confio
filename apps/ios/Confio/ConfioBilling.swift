// ConfioBilling (iOS): StoreKit 2 for the Confío IA+ subscription.
//
// The app never decides entitlement. Every purchase hands its signed
// transaction (JWS) to Django, which verifies it against Apple's root CA and
// the appAccountToken bound to the user; only then is the transaction
// finished. Unfinished transactions are redelivered through Transaction.updates
// (emitted as "ConfioBillingTransaction") until the server has them.
import Foundation
import StoreKit
import React

@objc(ConfioBilling)
class ConfioBilling: RCTEventEmitter {
  private var updatesTask: Task<Void, Never>?
  // Touched from the Transaction.updates task and from purchase/restore/finish
  // tasks: every access goes through `pendingLock`.
  private var pending: [UInt64: Transaction] = [:]
  private let pendingLock = NSLock()

  private func remember(_ transaction: Transaction) {
    pendingLock.lock(); defer { pendingLock.unlock() }
    pending[transaction.id] = transaction
  }

  private func takePending(_ id: UInt64) -> Transaction? {
    pendingLock.lock(); defer { pendingLock.unlock() }
    return pending.removeValue(forKey: id)
  }
  private var hasListeners = false

  override static func requiresMainQueueSetup() -> Bool { false }
  override func supportedEvents() -> [String]! { ["ConfioBillingTransaction"] }
  override func startObserving() { hasListeners = true; startUpdates() }
  override func stopObserving() { hasListeners = false }

  deinit { updatesTask?.cancel() }

  private func startUpdates() {
    guard updatesTask == nil else { return }
    updatesTask = Task.detached { [weak self] in
      for await result in Transaction.updates {
        guard let self = self else { return }
        if let payload = self.payload(for: result) {
          if self.hasListeners {
            self.sendEvent(withName: "ConfioBillingTransaction", body: payload)
          }
        }
      }
    }
  }

  /// Signed transaction for the server. Unverified ones are still forwarded:
  /// the server is the judge, and it rejects anything Apple didn't sign.
  private func payload(for result: VerificationResult<Transaction>) -> [String: Any]? {
    let transaction: Transaction
    switch result {
    case .verified(let t): transaction = t
    case .unverified(let t, _): transaction = t
    }
    remember(transaction)
    return [
      "platform": "ios",
      "productId": transaction.productID,
      "transactionId": String(transaction.id),
      "originalTransactionId": String(transaction.originalID),
      "signedTransaction": result.jwsRepresentation,
    ]
  }

  private func periodLabel(_ period: Product.SubscriptionPeriod?) -> String {
    guard let p = period else { return "" }
    let unit: String
    switch p.unit {
    case .day: unit = "D"
    case .week: unit = "W"
    case .month: unit = "M"
    case .year: unit = "Y"
    @unknown default: unit = "?"
    }
    return "P\(p.value)\(unit)"
  }

  @objc(getProducts:resolver:rejecter:)
  func getProducts(_ ids: [String], resolver resolve: @escaping RCTPromiseResolveBlock,
                   rejecter reject: @escaping RCTPromiseRejectBlock) {
    Task {
      do {
        let products = try await Product.products(for: ids)
        resolve(products.map { p -> [String: Any] in
          [
            "productId": p.id,
            "title": p.displayName,
            "description": p.description,
            "displayPrice": p.displayPrice,
            "price": NSDecimalNumber(decimal: p.price).stringValue,
            "currency": p.priceFormatStyle.currencyCode,
            "period": periodLabel(p.subscription?.subscriptionPeriod),
          ]
        })
      } catch {
        reject("PRODUCTS", "No pudimos cargar los planes.", error)
      }
    }
  }

  @objc(purchase:accountToken:resolver:rejecter:)
  func purchase(_ productId: String, accountToken: String,
                resolver resolve: @escaping RCTPromiseResolveBlock,
                rejecter reject: @escaping RCTPromiseRejectBlock) {
    guard let token = UUID(uuidString: accountToken) else {
      reject("ACCOUNT_TOKEN", "Cuenta inválida.", nil)
      return
    }
    Task {
      do {
        guard let product = try await Product.products(for: [productId]).first else {
          reject("PRODUCT", "Este plan no está disponible.", nil)
          return
        }
        let result = try await product.purchase(options: [.appAccountToken(token)])
        switch result {
        case .success(let verification):
          var body = self.payload(for: verification) ?? [:]
          body["status"] = "purchased"
          resolve(body)
        case .pending:
          resolve(["status": "pending"])
        case .userCancelled:
          resolve(["status": "cancelled"])
        @unknown default:
          resolve(["status": "cancelled"])
        }
      } catch {
        reject("PURCHASE", "No se pudo completar la compra.", error)
      }
    }
  }

  /// Every active subscription's signed transaction, for "Restaurar compras".
  @objc(currentEntitlements:rejecter:)
  func currentEntitlements(_ resolve: @escaping RCTPromiseResolveBlock,
                           rejecter reject: @escaping RCTPromiseRejectBlock) {
    Task {
      var items: [[String: Any]] = []
      for await result in Transaction.currentEntitlements {
        if let body = self.payload(for: result) { items.append(body) }
      }
      resolve(items)
    }
  }

  /// Called only after the server has recorded the transaction.
  @objc(finish:resolver:rejecter:)
  func finish(_ transactionId: String, resolver resolve: @escaping RCTPromiseResolveBlock,
              rejecter reject: @escaping RCTPromiseRejectBlock) {
    Task {
      if let id = UInt64(transactionId), let transaction = self.takePending(id) {
        await transaction.finish()
        resolve(true)
        return
      }
      // Not in memory (e.g. app restarted): find it among unfinished ones.
      for await result in Transaction.unfinished {
        let t: Transaction
        switch result { case .verified(let v): t = v; case .unverified(let v, _): t = v }
        if String(t.id) == transactionId {
          await t.finish()
          resolve(true)
          return
        }
      }
      resolve(false)
    }
  }

  @objc(manageSubscriptions:rejecter:)
  func manageSubscriptions(_ resolve: @escaping RCTPromiseResolveBlock,
                           rejecter reject: @escaping RCTPromiseRejectBlock) {
    Task { @MainActor in
      guard let scene = UIApplication.shared.connectedScenes
        .first(where: { $0.activationState == .foregroundActive }) as? UIWindowScene else {
        if let url = URL(string: "https://apps.apple.com/account/subscriptions") {
          await UIApplication.shared.open(url)
        }
        resolve(true)
        return
      }
      do {
        try await AppStore.showManageSubscriptions(in: scene)
        resolve(true)
      } catch {
        reject("MANAGE", "No pudimos abrir tus suscripciones.", error)
      }
    }
  }
}
