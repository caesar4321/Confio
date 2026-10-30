// The wallet's CloudKit copy, in the person's private database. The payload is a
// plain record field on purpose: encryptedValues depend on iCloud Keychain, and
// this copy exists for the people who have it off. Records are only ever
// inserted, so a backup can never be overwritten.
import CloudKit
import CryptoKit
import Foundation
import React

@objc(ConfioCloudBackup)
class ConfioCloudBackup: NSObject {
  private static let containerId = "iCloud.com.Confio.Confio"
  private static let recordType = "WalletBackup"
  private static let payloadField = "payload"

  private let container = CKContainer(identifier: ConfioCloudBackup.containerId)

  @objc static func requiresMainQueueSetup() -> Bool { false }

  private func configured(_ operation: CKDatabaseOperation) -> CKDatabaseOperation {
    let configuration = CKOperation.Configuration()
    configuration.qualityOfService = .userInitiated
    configuration.timeoutIntervalForRequest = 10
    configuration.timeoutIntervalForResource = 15
    operation.configuration = configuration
    operation.database = container.privateCloudDatabase
    return operation
  }

  private func rejectWithCode(_ error: Error, _ reject: RCTPromiseRejectBlock) {
    let code = (error as? CKError)?.errorCode ?? -1
    reject("CK_\(code)", "CloudKit error \(code)", error)
  }

  private func singleError(_ error: Error, _ recordID: CKRecord.ID) -> Error {
    guard let ckError = error as? CKError, ckError.code == .partialFailure,
          let inner = ckError.partialErrorsByItemID?[recordID] else { return error }
    return inner
  }

  @objc(accountStatus:rejecter:)
  func accountStatus(_ resolve: @escaping RCTPromiseResolveBlock,
                     rejecter reject: @escaping RCTPromiseRejectBlock) {
    container.accountStatus { status, error in
      if let error = error { self.rejectWithCode(error, reject); return }
      switch status {
      case .available: resolve("available")
      case .noAccount: resolve("noAccount")
      case .restricted: resolve("restricted")
      default: resolve("unknown")
      }
    }
  }

  /// Hash of the iCloud account's record name, so changing iCloud account
  /// starts a new backup without the app ever holding the identifier itself.
  @objc(userHash:rejecter:)
  func userHash(_ resolve: @escaping RCTPromiseResolveBlock,
                rejecter reject: @escaping RCTPromiseRejectBlock) {
    container.fetchUserRecordID { recordID, error in
      if let error = error { self.rejectWithCode(error, reject); return }
      guard let recordID = recordID else {
        reject("CK_NO_USER", "CloudKit returned no user", nil)
        return
      }
      let digest = SHA256.hash(data: Data(recordID.recordName.utf8))
      resolve(digest.map { String(format: "%02x", $0) }.joined())
    }
  }

  /// Resolves "inserted", or "exists" when the name is taken. Never updates.
  @objc(insert:payload:resolver:rejecter:)
  func insert(_ recordName: String, payload: String,
              resolver resolve: @escaping RCTPromiseResolveBlock,
              rejecter reject: @escaping RCTPromiseRejectBlock) {
    let recordID = CKRecord.ID(recordName: recordName)
    let record = CKRecord(recordType: ConfioCloudBackup.recordType, recordID: recordID)
    record[ConfioCloudBackup.payloadField] = payload as NSString
    let operation = CKModifyRecordsOperation(recordsToSave: [record], recordIDsToDelete: nil)
    operation.savePolicy = .ifServerRecordUnchanged
    operation.modifyRecordsCompletionBlock = { _, _, error in
      guard let error = error else { resolve("inserted"); return }
      let single = self.singleError(error, recordID)
      if (single as? CKError)?.code == .serverRecordChanged {
        resolve("exists")
      } else {
        self.rejectWithCode(single, reject)
      }
    }
    configured(operation).start()
  }

  /// Resolves the payload from Apple's servers, or null when no record exists.
  @objc(fetch:resolver:rejecter:)
  func fetch(_ recordName: String,
             resolver resolve: @escaping RCTPromiseResolveBlock,
             rejecter reject: @escaping RCTPromiseRejectBlock) {
    let recordID = CKRecord.ID(recordName: recordName)
    let operation = CKFetchRecordsOperation(recordIDs: [recordID])
    operation.fetchRecordsCompletionBlock = { records, error in
      if let record = records?[recordID] {
        resolve(record[ConfioCloudBackup.payloadField] as? String)
        return
      }
      if let error = error {
        let single = self.singleError(error, recordID)
        if (single as? CKError)?.code == .unknownItem {
          resolve(nil)
        } else {
          self.rejectWithCode(single, reject)
        }
        return
      }
      resolve(nil)
    }
    configured(operation).start()
  }
}
