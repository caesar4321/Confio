package com.confio;

import java.net.CookieManager;
import java.net.CookiePolicy;
import java.util.Collections;
import okhttp3.Cookie;
import okhttp3.HttpUrl;
import okhttp3.JavaNetCookieJar;
import org.junit.Test;
import static org.junit.Assert.assertEquals;

public class OkHttpCompatibilityTest {
    @Test
    public void reactNativeCookieJarCanLoadCookiesWithResolvedOkHttp() {
        JavaNetCookieJar jar = new JavaNetCookieJar(
                new CookieManager(null, CookiePolicy.ACCEPT_ALL));
        HttpUrl url = HttpUrl.get("https://example.com/");
        Cookie cookie = new Cookie.Builder().name("session").value("test")
                .hostOnlyDomain("example.com").path("/").build();
        jar.saveFromResponse(url, Collections.singletonList(cookie));
        assertEquals("test", jar.loadForRequest(url).get(0).value());
    }
}
