package com.Confio.Confio

import com.facebook.react.modules.network.OkHttpClientFactory
import com.facebook.react.modules.network.OkHttpClientProvider
import java.net.Inet4Address
import java.net.InetAddress
import java.util.concurrent.TimeUnit
import okhttp3.Dns
import okhttp3.OkHttpClient

/**
 * Some mobile-data hotspots (observed: Telecom Argentina tethering) advertise a
 * global IPv6 address but silently drop IPv6 traffic. Android then dials AAAA
 * records first and each connection stalls for the full OS TCP handshake
 * timeout (65-127s) before OkHttp tries the next address, so app startup takes
 * minutes. Dialing IPv4 first avoids the dead route entirely; IPv6-only
 * carriers keep working because 464xlat provides an IPv4 path. The bounded
 * connect timeout caps the cost of any remaining unreachable address, and
 * OkHttp's route database remembers failed routes for subsequent requests.
 */
private object Ipv4FirstDns : Dns {
  override fun lookup(hostname: String): List<InetAddress> =
      Dns.SYSTEM.lookup(hostname).sortedBy { if (it is Inet4Address) 0 else 1 }
}

class ConfioOkHttpClientFactory : OkHttpClientFactory {
  override fun createNewNetworkModuleClient(): OkHttpClient =
      OkHttpClientProvider.createClientBuilder()
          .connectTimeout(10, TimeUnit.SECONDS)
          .dns(Ipv4FirstDns)
          .build()
}
