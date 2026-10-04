package com.Confio.Confio

import android.content.Intent
import android.net.Uri
import com.android.billingclient.api.BillingClient
import com.android.billingclient.api.BillingClientStateListener
import com.android.billingclient.api.BillingFlowParams
import com.android.billingclient.api.BillingResult
import com.android.billingclient.api.PendingPurchasesParams
import com.android.billingclient.api.ProductDetails
import com.android.billingclient.api.Purchase
import com.android.billingclient.api.PurchasesUpdatedListener
import com.android.billingclient.api.QueryProductDetailsParams
import com.android.billingclient.api.QueryPurchasesParams
import com.facebook.react.ReactPackage
import com.facebook.react.bridge.*
import com.facebook.react.modules.core.DeviceEventManagerModule
import com.facebook.react.uimanager.ViewManager

// ConfioBilling (Android): Play Billing 8 for the Confío IA+ subscription.
//
// The app never decides entitlement and never acknowledges: every purchase
// token goes to Django, which reads it from the Play Developer API, checks the
// obfuscated account id bound to the user, and acknowledges server-side.
// Purchases made while the app was closed arrive as "ConfioBillingTransaction".
class ConfioBillingPackage : ReactPackage {
    override fun createNativeModules(context: ReactApplicationContext): List<NativeModule> = listOf(ConfioBillingModule(context))
    override fun createViewManagers(context: ReactApplicationContext): List<ViewManager<*, *>> = emptyList()
}

class ConfioBillingModule(private val context: ReactApplicationContext) :
    ReactContextBaseJavaModule(context), PurchasesUpdatedListener {

    override fun getName() = "ConfioBilling"

    private val products = mutableMapOf<String, ProductDetails>()
    private var purchasePromise: Promise? = null
    private var purchaseProductId: String? = null

    private val client: BillingClient by lazy {
        BillingClient.newBuilder(context)
            .setListener(this)
            .enablePendingPurchases(PendingPurchasesParams.newBuilder().enableOneTimeProducts().build())
            .enableAutoServiceReconnection()
            .build()
    }

    private fun withClient(promise: Promise, block: () -> Unit) {
        if (client.isReady) {
            block()
            return
        }
        client.startConnection(object : BillingClientStateListener {
            override fun onBillingSetupFinished(result: BillingResult) {
                if (result.responseCode == BillingClient.BillingResponseCode.OK) block()
                else promise.reject("BILLING_UNAVAILABLE", "Google Play no está disponible.")
            }
            override fun onBillingServiceDisconnected() {}
        })
    }

    private fun purchaseMap(p: Purchase): WritableMap = Arguments.createMap().apply {
        putString("platform", "android")
        putString("productId", p.products.firstOrNull() ?: "")
        putString("purchaseToken", p.purchaseToken)
        putString("orderId", p.orderId ?: "")
        putString("state", when (p.purchaseState) {
            Purchase.PurchaseState.PURCHASED -> "purchased"
            Purchase.PurchaseState.PENDING -> "pending"
            else -> "unknown"
        })
        putBoolean("acknowledged", p.isAcknowledged)
    }

    @ReactMethod
    fun addListener(eventName: String) {}

    @ReactMethod
    fun removeListeners(count: Int) {}

    @ReactMethod
    fun getProducts(ids: ReadableArray, promise: Promise) = withClient(promise) {
        val list = (0 until ids.size()).mapNotNull { ids.getString(it) }.map {
            QueryProductDetailsParams.Product.newBuilder()
                .setProductId(it)
                .setProductType(BillingClient.ProductType.SUBS)
                .build()
        }
        client.queryProductDetailsAsync(
            QueryProductDetailsParams.newBuilder().setProductList(list).build()
        ) { result, details ->
            if (result.responseCode != BillingClient.BillingResponseCode.OK) {
                promise.reject("PRODUCTS", "No pudimos cargar los planes.")
                return@queryProductDetailsAsync
            }
            val out = Arguments.createArray()
            for (pd in details.productDetailsList) {
                products[pd.productId] = pd
                // The base plan: the offer without a free-trial/intro phase.
                val offer = pd.subscriptionOfferDetails?.minByOrNull { it.pricingPhases.pricingPhaseList.size } ?: continue
                val phase = offer.pricingPhases.pricingPhaseList.lastOrNull() ?: continue
                out.pushMap(Arguments.createMap().apply {
                    putString("productId", pd.productId)
                    putString("title", pd.name)
                    putString("description", pd.description)
                    putString("displayPrice", phase.formattedPrice)
                    putString("price", (phase.priceAmountMicros / 1_000_000.0).toString())
                    putString("currency", phase.priceCurrencyCode)
                    putString("period", phase.billingPeriod)
                })
            }
            promise.resolve(out)
        }
    }

    @ReactMethod
    fun purchase(productId: String, accountToken: String, promise: Promise) = withClient(promise) {
        val activity = currentActivity
        val details = products[productId]
        val offer = details?.subscriptionOfferDetails?.minByOrNull { it.pricingPhases.pricingPhaseList.size }
        if (activity == null || details == null || offer == null) {
            promise.reject("PRODUCT", "Este plan no está disponible.")
            return@withClient
        }
        if (purchasePromise != null) {
            promise.reject("BUSY", "Ya hay una compra en curso.")
            return@withClient
        }
        purchasePromise = promise
        purchaseProductId = productId
        val params = BillingFlowParams.newBuilder()
            .setProductDetailsParamsList(listOf(
                BillingFlowParams.ProductDetailsParams.newBuilder()
                    .setProductDetails(details)
                    .setOfferToken(offer.offerToken)
                    .build()
            ))
            // Binds the purchase to the Confío user; checked server-side.
            .setObfuscatedAccountId(accountToken)
            .build()
        val result = client.launchBillingFlow(activity, params)
        if (result.responseCode != BillingClient.BillingResponseCode.OK) {
            purchasePromise = null
            promise.reject("PURCHASE", "No se pudo iniciar la compra.")
        }
    }

    override fun onPurchasesUpdated(result: BillingResult, purchases: MutableList<Purchase>?) {
        val promise = purchasePromise
        purchasePromise = null
        when (result.responseCode) {
            BillingClient.BillingResponseCode.OK -> {
                val mine = purchases?.firstOrNull { it.products.contains(purchaseProductId) } ?: purchases?.firstOrNull()
                if (promise != null && mine != null) {
                    promise.resolve(purchaseMap(mine).apply { putString("status", if (mine.purchaseState == Purchase.PurchaseState.PURCHASED) "purchased" else "pending") })
                } else {
                    // A purchase not started from this screen (renewal restore, pending completion).
                    purchases?.forEach { emit(purchaseMap(it)) }
                    promise?.resolve(Arguments.createMap().apply { putString("status", "cancelled") })
                }
            }
            BillingClient.BillingResponseCode.USER_CANCELED ->
                promise?.resolve(Arguments.createMap().apply { putString("status", "cancelled") })
            BillingClient.BillingResponseCode.ITEM_ALREADY_OWNED ->
                promise?.resolve(Arguments.createMap().apply { putString("status", "owned") })
            else -> promise?.reject("PURCHASE", "No se pudo completar la compra.")
        }
        purchaseProductId = null
    }

    private fun emit(map: WritableMap) {
        if (context.hasActiveReactInstance()) {
            context.getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java)
                .emit("ConfioBillingTransaction", map)
        }
    }

    @ReactMethod
    fun currentEntitlements(promise: Promise) = withClient(promise) {
        client.queryPurchasesAsync(
            QueryPurchasesParams.newBuilder().setProductType(BillingClient.ProductType.SUBS).build()
        ) { result, purchases ->
            if (result.responseCode != BillingClient.BillingResponseCode.OK) {
                promise.reject("RESTORE", "No pudimos consultar tus compras.")
                return@queryPurchasesAsync
            }
            val out = Arguments.createArray()
            purchases.forEach { out.pushMap(purchaseMap(it)) }
            promise.resolve(out)
        }
    }

    /** iOS-only concept; acknowledgment happens on the server. */
    @ReactMethod
    fun finish(transactionId: String, promise: Promise) = promise.resolve(true)

    @ReactMethod
    fun manageSubscriptions(promise: Promise) {
        val url = "https://play.google.com/store/account/subscriptions?package=${context.packageName}"
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
        promise.resolve(true)
    }
}
