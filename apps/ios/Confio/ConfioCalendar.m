// Debug-only until the release gates in docs/designs/assistant-mail-calendar.md are met.
#if DEBUG
#import <React/RCTBridgeModule.h>
@interface RCT_EXTERN_MODULE(ConfioCalendar, NSObject)
RCT_EXTERN_METHOD(permissionStatus:(RCTPromiseResolveBlock)resolve rejecter:(RCTPromiseRejectBlock)reject)
RCT_EXTERN_METHOD(requestAccess:(RCTPromiseResolveBlock)resolve rejecter:(RCTPromiseRejectBlock)reject)
RCT_EXTERN_METHOD(listCalendars:(RCTPromiseResolveBlock)resolve rejecter:(RCTPromiseRejectBlock)reject)
RCT_EXTERN_METHOD(listEvents:(NSArray *)calendarIds from:(double)from until:(double)until resolver:(RCTPromiseResolveBlock)resolve rejecter:(RCTPromiseRejectBlock)reject)
@end
#endif
