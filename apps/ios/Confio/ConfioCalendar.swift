// Read-only EventKit for Confío IA (docs/designs/assistant-mail-calendar.md).
import CryptoKit
import EventKit
import Foundation
import React

@objc(ConfioCalendar)
final class ConfioCalendar: NSObject {
  private static let maxWindowMs: Double = 31 * 86_400_000
  private static let maxEvents = 200
  // EventKit drops a request whose store was released.
  private var requestStore: EKEventStore?

  @objc static func requiresMainQueueSetup() -> Bool { false }

  private var granted: Bool {
    let status = EKEventStore.authorizationStatus(for: .event)
    if #available(iOS 17.0, *) { return status == .fullAccess }
    return status == .authorized
  }

  @objc(permissionStatus:rejecter:)
  func permissionStatus(resolve: @escaping RCTPromiseResolveBlock, reject: @escaping RCTPromiseRejectBlock) {
    resolve(granted ? "granted" : "denied")
  }

  // The purpose strings are not in Info.plist until release (design doc, "Release gates").
  // Asking without one does not work, so say so instead.
  private var hasPurposeString: Bool {
    let has = { (key: String) in Bundle.main.object(forInfoDictionaryKey: key) != nil }
    if #available(iOS 17.0, *) {
      return has("NSCalendarsFullAccessUsageDescription") || has("NSCalendarsUsageDescription")
    }
    return has("NSCalendarsUsageDescription")
  }

  @objc(requestAccess:rejecter:)
  func requestAccess(resolve: @escaping RCTPromiseResolveBlock, reject: @escaping RCTPromiseRejectBlock) {
    if granted {
      resolve("granted")
      return
    }
    guard hasPurposeString else {
      resolve("unavailable")
      return
    }
    let store = EKEventStore()
    requestStore = store
    let done: EKEventStoreRequestAccessCompletionHandler = { allowed, _ in
      resolve(allowed ? "granted" : "denied")
    }
    if #available(iOS 17.0, *) {
      store.requestFullAccessToEvents(completion: done)
    } else {
      store.requestAccess(to: .event, completion: done)
    }
  }

  // Subscribed calendars are where calendar spam lives; birthdays are contacts.
  private func readable(_ store: EKEventStore) -> [EKCalendar] {
    store.calendars(for: .event).filter { $0.type != .subscription && $0.type != .birthday }
  }

  @objc(listCalendars:rejecter:)
  func listCalendars(resolve: @escaping RCTPromiseResolveBlock, reject: @escaping RCTPromiseRejectBlock) {
    guard granted else {
      reject("CALENDAR_PERMISSION", "Calendar access is not granted.", nil)
      return
    }
    let store = EKEventStore()
    resolve(readable(store).map { calendar -> [String: Any] in
      ["id": calendar.calendarIdentifier, "title": calendar.title, "account": calendar.source?.title ?? ""]
    })
  }

  @objc(listEvents:from:until:resolver:rejecter:)
  func listEvents(
    calendarIds: NSArray, from: Double, until: Double,
    resolve: @escaping RCTPromiseResolveBlock, reject: @escaping RCTPromiseRejectBlock
  ) {
    guard granted else {
      reject("CALENDAR_PERMISSION", "Calendar access is not granted.", nil)
      return
    }
    guard until > from, until - from <= Self.maxWindowMs else {
      reject("CALENDAR_WINDOW", "Invalid window.", nil)
      return
    }
    let store = EKEventStore()
    let wanted = Set(calendarIds.compactMap { $0 as? String })
    let chosen = readable(store).filter { wanted.contains($0.calendarIdentifier) }
    // Never hand EventKit an empty or nil list: that searches every calendar.
    guard !chosen.isEmpty else {
      resolve([])
      return
    }
    let predicate = store.predicateForEvents(
      withStart: Date(timeIntervalSince1970: from / 1000),
      end: Date(timeIntervalSince1970: until / 1000),
      calendars: chosen)
    let events = store.events(matching: predicate)
      .filter { $0.status != .canceled && Self.accepted($0) }
      .sorted { $0.compareStartDate(with: $1) == .orderedAscending }
      .prefix(Self.maxEvents)
    resolve(events.compactMap { event -> [String: Any]? in
      guard let start = event.startDate else { return nil }
      let startsAt = (start.timeIntervalSince1970 * 1000).rounded()
      let key = event.eventIdentifier ?? event.calendarItemIdentifier
      return [
        "id": Self.opaque("\(key):\(Int64(startsAt))"),
        "title": String((event.title ?? "").prefix(300)),
        "startsAt": startsAt,
        "allDay": event.isAllDay,
      ]
    })
  }

  // The identifier can embed the organizer's UID, often an email address.
  private static func opaque(_ value: String) -> String {
    SHA256.hash(data: Data(value.utf8)).prefix(16).map { String(format: "%02x", $0) }.joined()
  }

  // An invitation the person hasn't accepted is someone else's text: leave it out.
  private static func accepted(_ event: EKEvent) -> Bool {
    if let me = event.attendees?.first(where: { $0.isCurrentUser }) {
      return me.participantStatus == .accepted || me.participantStatus == .tentative
        || event.organizer?.isCurrentUser == true
    }
    guard let organizer = event.organizer else { return true }
    return organizer.isCurrentUser
  }
}
