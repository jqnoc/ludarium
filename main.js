/**
 * Ludarium — Electron main process.
 *
 * Starts the local Flask backend, waits for it to accept connections, and
 * opens the renderer in a frameless desktop window.
 */

const { app, BrowserWindow, ipcMain, shell } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const net = require("net");

// Prevent blank native-background windows on systems with unreliable GPU compositing.
app.disableHardwareAcceleration();

let mainWindow = null;
let splashWindow = null;
let flaskProcess = null;
let flaskPort = 0;
let rendererRecoveryAttempts = 0;
let rendererRecoveryTimer = null;

const isPackaged = app.isPackaged;
const appRoot = isPackaged ? path.join(process.resourcesPath, "app") : __dirname;
const PREFERRED_PORT = 48742;

function findFreePort() {
  return new Promise((resolve, reject) => {
    const preferred = net.createServer();
    preferred.listen(PREFERRED_PORT, "127.0.0.1", () => {
      preferred.close(() => resolve(PREFERRED_PORT));
    });
    preferred.on("error", () => {
      const fallback = net.createServer();
      fallback.listen(0, "127.0.0.1", () => {
        const address = fallback.address();
        fallback.close(() => resolve(address.port));
      });
      fallback.on("error", reject);
    });
  });
}

function resolveBackend() {
  if (isPackaged) {
    return {
      command: path.join(
        process.resourcesPath,
        "backend",
        process.platform === "win32" ? "ludarium-backend.exe" : "ludarium-backend",
      ),
      args: [],
      cwd: path.join(process.resourcesPath, "backend"),
    };
  }

  const projectPython = path.join(
    appRoot,
    ".venv",
    process.platform === "win32" ? "Scripts" : "bin",
    process.platform === "win32" ? "python.exe" : "python",
  );
  const command = fs.existsSync(projectPython)
    ? projectPython
    : process.platform === "win32" ? "python" : "python3";
  return { command, args: [path.join(appRoot, "app.py")], cwd: appRoot };
}

function resolveDataDir() {
  if (process.env.LUDARIUM_DATA_DIR) return process.env.LUDARIUM_DATA_DIR;
  if (isPackaged) return path.join(app.getPath("userData"), "data");
  return path.join(appRoot, "data");
}

function startFlask(port) {
  const backend = resolveBackend();
  flaskProcess = spawn(backend.command, backend.args, {
    cwd: backend.cwd,
    env: {
      ...process.env,
      LUDARIUM_PORT: String(port),
      LUDARIUM_ELECTRON: "1",
      LUDARIUM_DATA_DIR: resolveDataDir(),
      PYTHONIOENCODING: "utf-8",
    },
    stdio: "pipe",
    windowsHide: true,
  });

  flaskProcess.stdout.on("data", (data) => {
    console.log(`[Flask] ${data.toString().trim()}`);
  });
  flaskProcess.stderr.on("data", (data) => {
    console.log(`[Flask] ${data.toString().trim()}`);
  });
  flaskProcess.on("error", (error) => {
    console.error(`Failed to start Flask: ${error.message}`);
  });
  flaskProcess.on("close", (code) => {
    console.log(`Flask process exited with code ${code}`);
    flaskProcess = null;
  });
}

function waitForFlask(port, retries = 120, interval = 250) {
  return new Promise((resolve, reject) => {
    let attempt = 0;
    const check = () => {
      const socket = net.createConnection({ port, host: "127.0.0.1" }, () => {
        socket.destroy();
        resolve();
      });
      socket.on("error", () => {
        attempt += 1;
        if (attempt >= retries) {
          reject(new Error("Flask server did not start in time"));
        } else {
          setTimeout(check, interval);
        }
      });
    };
    check();
  });
}

function notifyWindowState() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents.send("window-state-changed", mainWindow.isMaximized());
}

function killFlask() {
  if (!flaskProcess) return;
  if (process.platform === "win32") {
    spawn("taskkill", ["/pid", String(flaskProcess.pid), "/f", "/t"], {
      windowsHide: true,
    });
  } else {
    flaskProcess.kill("SIGTERM");
  }
  flaskProcess = null;
}

function rendererUrl() {
  return `http://127.0.0.1:${flaskPort}`;
}

function showRendererError(message) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const escapedMessage = String(message)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .slice(0, 240);
  const escapedUrl = rendererUrl().replace(/"/g, "&quot;");
  const html = `<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Ludarium - Load error</title>
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;color:#edf2f7;background:#16223b;font:16px "Segoe UI",sans-serif}
main{max-width:620px;padding:2rem;text-align:center}
h1{color:#ffb36b}
p{color:#c7d2e3;line-height:1.6}
code{display:block;margin:1rem 0;padding:.75rem;overflow-wrap:anywhere;color:#f7cfa8;background:#0d152a;border-radius:6px}
button{padding:.7rem 1.2rem;border:0;border-radius:6px;color:#fff;background:#168f83;cursor:pointer;font:inherit}
</style></head>
<body><main><h1>Ludarium could not load</h1>
<p>The local application page failed to render. Retry the page or restart Ludarium.</p>
<code>${escapedMessage}</code>
<button onclick="location.href=&quot;${escapedUrl}&quot;">Retry</button>
</main></body></html>`;
  mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`).catch((error) => {
    console.error(`Failed to show renderer error page: ${error.message}`);
  });
}

function recoverRenderer(message) {
  if (!mainWindow || mainWindow.isDestroyed() || rendererRecoveryTimer) return;
  if (rendererRecoveryAttempts < 2) {
    rendererRecoveryAttempts += 1;
    rendererRecoveryTimer = setTimeout(() => {
      rendererRecoveryTimer = null;
      if (!mainWindow || mainWindow.isDestroyed()) return;
      mainWindow.loadURL(rendererUrl()).catch((error) => {
        recoverRenderer(error.message);
      });
    }, 300);
    return;
  }
  showRendererError(message);
}

async function createWindow() {
  splashWindow = new BrowserWindow({
    width: 340,
    height: 360,
    frame: false,
    transparent: true,
    resizable: false,
    alwaysOnTop: true,
    title: "Ludarium",
    icon: path.join(appRoot, "static", "logo.png"),
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  splashWindow.loadFile(path.join(appRoot, "static", "splash.html"));
  splashWindow.once("ready-to-show", () => splashWindow.show());

  try {
    flaskPort = await findFreePort();
    startFlask(flaskPort);
    await waitForFlask(flaskPort);
  } catch (error) {
    console.error(error.message);
    if (splashWindow) splashWindow.close();
    app.quit();
    return;
  }

  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 900,
    minHeight: 620,
    title: "Ludarium",
    icon: path.join(appRoot, "static", "logo.png"),
    backgroundColor: "#16223b",
    show: false,
    frame: false,
    maximizable: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      backgroundThrottling: false,
    },
  });

  mainWindow.on("maximize", notifyWindowState);
  mainWindow.on("unmaximize", notifyWindowState);
  mainWindow.webContents.on("did-finish-load", () => {
    if (
      mainWindow &&
      !mainWindow.isDestroyed() &&
      mainWindow.webContents.getURL().startsWith(rendererUrl())
    ) {
      rendererRecoveryAttempts = 0;
    }
  });
  mainWindow.webContents.on(
    "did-fail-load",
    (_event, errorCode, errorDescription, validatedURL, isMainFrame) => {
      if (!isMainFrame || errorCode === -3 || validatedURL.startsWith("data:")) return;
      console.error(
        `Renderer failed to load ${validatedURL}: ${errorCode} ${errorDescription}`,
      );
      recoverRenderer(`${errorCode} ${errorDescription}`);
    },
  );
  mainWindow.webContents.on("render-process-gone", (_event, details) => {
    console.error(`Renderer process exited: ${details.reason} (${details.exitCode})`);
    recoverRenderer(`Renderer process exited: ${details.reason}`);
  });
  mainWindow.loadURL(rendererUrl()).catch((error) => {
    recoverRenderer(error.message);
  });
  mainWindow.once("ready-to-show", () => {
    mainWindow.maximize();
    mainWindow.show();
    notifyWindowState();
    if (splashWindow) {
      splashWindow.close();
      splashWindow = null;
    }
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("http") && !url.includes(`127.0.0.1:${flaskPort}`)) {
      shell.openExternal(url);
      return { action: "deny" };
    }
    return { action: "allow" };
  });
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

ipcMain.on("app-quit", () => app.quit());
ipcMain.on("app-minimize", () => {
  if (mainWindow) mainWindow.minimize();
});
ipcMain.on("app-toggle-maximize", () => {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (mainWindow.isMaximized()) mainWindow.unmaximize();
  else mainWindow.maximize();
});
ipcMain.handle("app-window-state", () => ({
  isMaximized: Boolean(mainWindow && mainWindow.isMaximized()),
}));

app.whenReady().then(createWindow);
app.on("window-all-closed", () => {
  killFlask();
  app.quit();
});
app.on("before-quit", killFlask);
