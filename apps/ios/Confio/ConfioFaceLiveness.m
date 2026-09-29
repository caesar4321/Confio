#import <React/RCTBridgeModule.h>
@interface RCT_EXTERN_MODULE(ConfioFaceLiveness, NSObject)
RCT_EXTERN_METHOD(start:(NSString *)sessionId region:(NSString *)region credentials:(NSDictionary *)credentials resolver:(RCTPromiseResolveBlock)resolve rejecter:(RCTPromiseRejectBlock)reject)
@end
