import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("electronAPI", {
  getConfig: () => ipcRenderer.invoke("get-config"),
  setClickThrough: (enabled: boolean) =>
    ipcRenderer.invoke("set-click-through", enabled),
  startDrag: () => ipcRenderer.invoke("start-drag"),
  moveWindow: (deltaX: number, deltaY: number) =>
    ipcRenderer.invoke("move-window", deltaX, deltaY),
  resizeWindow: (bounds: {
    x: number;
    y: number;
    width: number;
    height: number;
  }) => ipcRenderer.invoke("resize-window", bounds),
  closeApp: () => ipcRenderer.invoke("close-app"),
  setAlwaysOnTop: (enabled: boolean) =>
    ipcRenderer.invoke("set-always-on-top", enabled),
  setOpacity: (opacity: number) =>
    ipcRenderer.invoke("set-opacity", opacity),
  getCursorWindowPoint: () => ipcRenderer.invoke("get-cursor-window-point"),
  getModelOverrides: () => ipcRenderer.invoke("get-model-overrides"),
  onGlobalPointer: (callback: (windowX: number, windowY: number) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, x: number, y: number) =>
      callback(x, y);
    ipcRenderer.on("global-pointer", handler);
    return () => ipcRenderer.removeListener("global-pointer", handler);
  },
});
