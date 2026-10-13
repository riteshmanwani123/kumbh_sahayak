package org.kumbhsahayak.app;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.media.AudioManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.WindowInsets;
import android.widget.FrameLayout;
import android.webkit.CookieManager;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

/**
 * Kumbh Sahayak — a thin Android shell around the deployed web app.
 * The voice call (OpenAI Realtime over WebRTC) runs inside the WebView; this class only grants the
 * microphone, opens tel:/maps links in the right apps, and shows an offline screen.
 */
public class MainActivity extends Activity {
    private static final int REQ_MIC = 42;

    private WebView web;
    private PermissionRequest pendingWebPermission;
    private final String appUrl = BuildConfig.APP_URL;
    private final String appHost = Uri.parse(BuildConfig.APP_URL).getHost();

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setVolumeControlStream(AudioManager.STREAM_VOICE_CALL);

        web = new WebView(this);
        web.setBackgroundColor(0xFFFBF7F0);
        // WebView ignores its own padding, so pad a container instead.
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(0xFFFBF7F0);
        root.addView(web, new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));
        setContentView(root);
        // Android 15+ draws apps edge-to-edge: keep the page clear of the status bar, nav bar and keyboard.
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            int l, t, r, b;
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets i = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.ime());
                l = i.left; t = i.top; r = i.right; b = i.bottom;
            } else {
                l = insets.getSystemWindowInsetLeft(); t = insets.getSystemWindowInsetTop();
                r = insets.getSystemWindowInsetRight(); b = insets.getSystemWindowInsetBottom();
            }
            v.setPadding(l, t, r, b);
            return insets;
        });

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);                 // caller ID + access code live in localStorage
        s.setMediaPlaybackRequiresUserGesture(false); // assistant's voice plays without an extra tap
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        s.setUserAgentString(s.getUserAgentString() + " KumbhSahayakApp/" + BuildConfig.VERSION_NAME);
        CookieManager.getInstance().setAcceptCookie(true);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                String scheme = uri.getScheme() == null ? "" : uri.getScheme();
                if (scheme.equals("tel")) {                       // "Emergency 112" etc. → phone dialer
                    openExternal(new Intent(Intent.ACTION_DIAL, uri));
                    return true;
                }
                if (appHost != null && appHost.equalsIgnoreCase(uri.getHost())) {
                    return false;                                 // stay inside the app
                }
                openExternal(new Intent(Intent.ACTION_VIEW, uri)); // Google Maps / OSM / sources
                return true;
            }

            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) {
                view.setVisibility(View.VISIBLE);
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) {
                    view.loadDataWithBaseURL(null, offlinePage(), "text/html", "utf-8", null);
                }
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(final PermissionRequest request) {
                runOnUiThread(() -> {
                    boolean wantsMic = false;
                    for (String r : request.getResources()) {
                        if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(r)) wantsMic = true;
                    }
                    if (!wantsMic) { request.deny(); return; }
                    if (hasMic()) {
                        request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
                    } else {
                        pendingWebPermission = request;
                        requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_MIC);
                    }
                });
            }
        });

        if (savedInstanceState != null) web.restoreState(savedInstanceState);
        else web.loadUrl(appUrl);
    }

    private boolean hasMic() {
        return Build.VERSION.SDK_INT < 23
                || checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED;
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] results) {
        super.onRequestPermissionsResult(code, perms, results);
        if (code != REQ_MIC || pendingWebPermission == null) return;
        if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) {
            pendingWebPermission.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
        } else {
            pendingWebPermission.deny();
            Toast.makeText(this, R.string.mic_needed, Toast.LENGTH_LONG).show();
        }
        pendingWebPermission = null;
    }

    private void openExternal(Intent i) {
        try { startActivity(i); }
        catch (ActivityNotFoundException e) { Toast.makeText(this, i.getDataString(), Toast.LENGTH_LONG).show(); }
    }

    private String offlinePage() {
        return "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head>"
             + "<body style='font-family:sans-serif;background:#FBF7F0;color:#1f1a14;padding:32px;text-align:center'>"
             + "<h2>No internet connection</h2><p>Kumbh Sahayak needs internet. Please check your connection.</p>"
             + "<p><a href='tel:112' style='display:inline-block;background:#c62828;color:#fff;padding:12px 20px;"
             + "border-radius:24px;text-decoration:none;font-weight:bold'>Emergency: call 112</a></p>"
             + "<p><a href='" + appUrl + "' style='color:#E0661B'>Try again</a></p></body></html>";
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack(); else super.onBackPressed();
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    protected void onDestroy() {
        if (web != null) { web.loadUrl("about:blank"); web.destroy(); }
        super.onDestroy();
    }
}
