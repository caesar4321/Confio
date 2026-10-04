#import <React/RCTBridgeModule.h>
@interface RCT_EXTERN_MODULE(ConfioAudioRoute, NSObject)
RCT_EXTERN_METHOD(setSpeaker:(BOOL)on resolver:(RCTPromiseResolveBlock)resolve rejecter:(RCTPromiseRejectBlock)reject)
RCT_EXTERN_METHOD(impact)
@end
