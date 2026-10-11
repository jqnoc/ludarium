/**
 * Ludarium — Electron preload script.
 *
 * The renderer only receives the small set of window controls it needs.
 */

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("ludarium", {
  isElectron: true,
  quit: () => ipcRenderer.send("app-quit"),
  minimize: () => ipcRenderer.send("app-minimize"),
  toggleMaximize: () => ipcRenderer.send("app-toggle-maximize"),
  getWindowState: () => ipcRenderer.invoke("app-window-state"),
  onWindowStateChanged: (callback) => {
    if (typeof callback !== "function") return () => {};
    const listener = (_event, isMaximized) => callback(Boolean(isMaximized));
    ipcRenderer.on("window-state-changed", listener);
    return () => ipcRenderer.removeListener("window-state-changed", listener);
  },
});
