// E06-T01 minimal Tauri v2 host. It does exactly three things and nothing else, so we
// measure WebView2 and not our Rust: (1) open ONE window on the runner's loopback URL
// (CV_MATRIX_URL), (2) append the Tauri version and the REAL WebView2 runtime version
// to the URL query (sv_tauri, sv_webview2) so run-matrix.mjs records them in the manifest,
// (3) exit when the window closes. No custom commands, no IPC, no plugins.
// The WebView2 version is read with tauri's own `webview_version()` (the runtime actually
// loaded, which is OS-updated and is the whole point of this arm; ADR-0011).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::{WebviewUrl, WebviewWindowBuilder};

fn main() {
    let base = std::env::var("CV_MATRIX_URL").expect("CV_MATRIX_URL must be set by run-matrix.mjs");
    let webview2 = tauri::webview_version().unwrap_or_else(|_| "unknown".to_string());
    let tauri_version = tauri::VERSION;
    let sep = if base.contains('?') { '&' } else { '?' };
    let url = format!("{base}{sep}sv_tauri={tauri_version}&sv_webview2={webview2}");

    tauri::Builder::default()
        .setup(move |app| {
            let parsed = url.parse().expect("valid CV_MATRIX_URL");
            WebviewWindowBuilder::new(app, "main", WebviewUrl::External(parsed))
                .title("CandleViewer matrix (Tauri/WebView2)")
                .inner_size(1700.0, 1000.0)
                .build()?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("tauri run failed");
}
