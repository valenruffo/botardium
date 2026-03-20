use std::io::{Read, Write};
use std::net::TcpStream;
use std::process::Command;
use std::thread;
use std::time::{Duration, Instant};

use serde_json::Value;

const API_HOST: &str = "127.0.0.1";
const API_PORT: u16 = 8000;
const API_BASE_URL: &str = "http://127.0.0.1:8000";
const API_READY_TIMEOUT: Duration = Duration::from_secs(25);
const API_READY_POLL_INTERVAL: Duration = Duration::from_millis(350);
const APP_VERSION: &str = env!("CARGO_PKG_VERSION");

fn backend_health_response() -> Option<String> {
  let address = format!("{}:{}", API_HOST, API_PORT);
  let mut stream = match TcpStream::connect(address) {
    Ok(stream) => stream,
    Err(_) => return None,
  };

  let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
  let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));

  let request = format!(
    "GET /health HTTP/1.1\r\nHost: {}:{}\r\nConnection: close\r\n\r\n",
    API_HOST, API_PORT
  );

  if stream.write_all(request.as_bytes()).is_err() {
    return None;
  }

  let mut response = String::new();
  if stream.read_to_string(&mut response).is_err() {
    return None;
  }

  Some(response)
}

fn backend_healthcheck() -> bool {
  matches!(
    backend_health_response().as_deref(),
    Some(response) if response.starts_with("HTTP/1.1 200") || response.starts_with("HTTP/1.0 200")
  )
}

fn backend_version() -> Option<String> {
  let response = backend_health_response()?;
  if !(response.starts_with("HTTP/1.1 200") || response.starts_with("HTTP/1.0 200")) {
    return None;
  }
  let body = response.split("\r\n\r\n").nth(1)?;
  let payload: Value = serde_json::from_str(body).ok()?;
  payload.get("version")?.as_str().map(|value| value.to_string())
}

fn kill_stale_backend() {
  #[cfg(target_os = "windows")]
  {
    let _ = Command::new("taskkill")
      .args(["/IM", "botardium-api.exe", "/F"])
      .status();
    thread::sleep(Duration::from_millis(600));
  }
}

fn wait_for_backend_ready() -> bool {
  let deadline = Instant::now() + API_READY_TIMEOUT;
  while Instant::now() < deadline {
    if backend_healthcheck() {
      return true;
    }
    thread::sleep(API_READY_POLL_INTERVAL);
  }
  false
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .plugin(tauri_plugin_process::init())
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }
      app.handle().plugin(tauri_plugin_shell::init())?;
      app.handle().plugin(tauri_plugin_dialog::init())?;
      #[cfg(desktop)]
      app.handle().plugin(tauri_plugin_updater::Builder::new().build())?;
      
      #[cfg(desktop)]
      {
        use tauri_plugin_shell::ShellExt;
        let backend_matches = matches!(backend_version().as_deref(), Some(version) if version == APP_VERSION);
        if backend_healthcheck() && !backend_matches {
          kill_stale_backend();
        }

        if !backend_healthcheck() {
          let sidecar_command = app.handle().shell().sidecar("botardium-api")
            .expect("failed to create sidecar command")
            .env("BOTARDIUM_API_BASE_URL", API_BASE_URL);
          let (_rx, _child) = sidecar_command.spawn()
            .expect("failed to spawn sidecar");
        }

        if !wait_for_backend_ready() {
          return Err(format!(
            "Botardium no pudo iniciar el backend local en {} dentro del timeout esperado.",
            API_BASE_URL
          ).into());
        }
      }
      
      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
