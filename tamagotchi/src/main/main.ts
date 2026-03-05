import {
  app,
  BrowserWindow,
  ipcMain,
  Tray,
  Menu,
  nativeImage,
  screen,
} from "electron";
import * as fs from "fs";
import * as path from "path";
import {
  loadConfigFromYaml,
  loadWindowState,
  saveWindowState,
  type AppConfig,
} from "./config-loader";

const jsautogui = require("jsautogui") as {
  mouse: {
    getPosition: () => { x: number; y: number };
  };
};

declare const MAIN_WINDOW_VITE_DEV_SERVER_URL: string | undefined;
declare const MAIN_WINDOW_VITE_NAME: string;

let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let appConfig: AppConfig;
let globalPointerTimer: ReturnType<typeof setInterval> | null = null;

function startGlobalPointerTracking(): void {
  if (globalPointerTimer) {
    clearInterval(globalPointerTimer);
    globalPointerTimer = null;
  }

  globalPointerTimer = setInterval(() => {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    let point = screen.getCursorScreenPoint();
    try {
      const nativePoint = jsautogui.mouse.getPosition();
      if (Number.isFinite(nativePoint.x) && Number.isFinite(nativePoint.y)) {
        point = nativePoint;
      }
    } catch {
      // fall back to Electron cursor position
    }

    const display = screen.getDisplayNearestPoint(point).bounds;
    const edgeThreshold = 2;
    const edgeExtend = 2000;

    let adjustedX = point.x;
    let adjustedY = point.y;

    if (point.x <= display.x + edgeThreshold) {
      adjustedX = display.x - edgeExtend;
    } else if (point.x >= display.x + display.width - 1 - edgeThreshold) {
      adjustedX = display.x + display.width + edgeExtend;
    }

    if (point.y <= display.y + edgeThreshold) {
      adjustedY = display.y - edgeExtend;
    } else if (point.y >= display.y + display.height - 1 - edgeThreshold) {
      adjustedY = display.y + display.height + edgeExtend;
    }

    const bounds = mainWindow.getBounds();
    const localX = adjustedX - bounds.x;
    const localY = adjustedY - bounds.y;
    mainWindow.webContents.send("global-pointer", localX, localY);
  }, 16);
}

function stopGlobalPointerTracking(): void {
  if (!globalPointerTimer) return;
  clearInterval(globalPointerTimer);
  globalPointerTimer = null;
}

function createWindow(): void {
  const tc = appConfig.tamagotchi;

  const savedState = loadWindowState({
    width: tc.window_width,
    height: tc.window_height,
  });

  mainWindow = new BrowserWindow({
    width: savedState.width,
    height: savedState.height,
    x: savedState.x,
    y: savedState.y,
    transparent: true,
    backgroundColor: "#00000000",
    frame: false,
    alwaysOnTop: tc.always_on_top,
    hasShadow: false,
    resizable: true,
    skipTaskbar: false,
    show: false, // Don't show until ready-to-show
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      backgroundThrottling: false,
    },
  });

  mainWindow.setOpacity(tc.opacity);

  // DON'T enable click-through at startup — it makes the window uninteractable.
  // The renderer will manage click-through dynamically via IPC.

  if (MAIN_WINDOW_VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(MAIN_WINDOW_VITE_DEV_SERVER_URL);
  } else {
    mainWindow.loadFile(
      path.join(__dirname, `../renderer/${MAIN_WINDOW_VITE_NAME}/index.html`)
    );
  }

  // Show window once content is ready
  mainWindow.once("ready-to-show", () => {
    console.log("[main] ready-to-show fired");
    mainWindow?.show();
    mainWindow?.focus();
    // Open devtools in dev mode for debugging
    if (MAIN_WINDOW_VITE_DEV_SERVER_URL) {
      mainWindow?.webContents.openDevTools({ mode: "detach" });
    }
  });

  // Fallback: force show after 3 seconds if ready-to-show didn't fire
  setTimeout(() => {
    if (mainWindow && !mainWindow.isVisible()) {
      console.log("[main] fallback show");
      mainWindow.show();
      mainWindow.focus();
    }
  }, 3000);

  startGlobalPointerTracking();

  // Save window state on move/resize
  const saveState = () => {
    if (!mainWindow) return;
    const bounds = mainWindow.getBounds();
    saveWindowState(bounds);
  };
  mainWindow.on("moved", saveState);
  mainWindow.on("resized", saveState);

  mainWindow.on("closed", () => {
    stopGlobalPointerTracking();
    mainWindow = null;
  });
}

function createTray(): void {
  // Create a small 16x16 colored icon for the tray
  const iconSize = 16;
  const canvas = Buffer.alloc(iconSize * iconSize * 4);
  for (let i = 0; i < iconSize * iconSize; i++) {
    canvas[i * 4] = 100; // R
    canvas[i * 4 + 1] = 149; // G
    canvas[i * 4 + 2] = 237; // B
    canvas[i * 4 + 3] = 255; // A
  }
  const icon = nativeImage.createFromBuffer(canvas, {
    width: iconSize,
    height: iconSize,
  });

  try {
    tray = new Tray(icon);
    tray.setToolTip("Open-LLM-VTuber Pet");

    const contextMenu = Menu.buildFromTemplate([
      {
        label: "Show/Hide",
        click: () => {
          if (mainWindow?.isVisible()) {
            mainWindow.hide();
          } else {
            mainWindow?.show();
            mainWindow?.focus();
          }
        },
      },
      { type: "separator" },
      {
        label: "Quit",
        click: () => {
          app.quit();
        },
      },
    ]);

    tray.setContextMenu(contextMenu);
    tray.on("click", () => {
      mainWindow?.show();
      mainWindow?.focus();
    });
  } catch (err) {
    console.warn("Failed to create tray icon:", err);
    // Tray is optional, continue without it
  }
}

// IPC Handlers
function setupIPC(): void {
  ipcMain.handle("get-config", () => {
    return appConfig;
  });

  ipcMain.handle("set-click-through", (_event, enabled: boolean) => {
    if (!mainWindow) return;
    if (enabled) {
      mainWindow.setIgnoreMouseEvents(true, { forward: true });
    } else {
      mainWindow.setIgnoreMouseEvents(false);
    }
  });

  ipcMain.handle("start-drag", () => {
    // The renderer will handle mouse-based drag via window movement
  });

  ipcMain.handle("move-window", (_event, deltaX: number, deltaY: number) => {
    if (!mainWindow) return;
    const [x, y] = mainWindow.getPosition();
    mainWindow.setPosition(x + deltaX, y + deltaY);
  });

  ipcMain.handle(
    "resize-window",
    (
      _event,
      bounds: { x: number; y: number; width: number; height: number }
    ) => {
      if (!mainWindow) return;
      mainWindow.setBounds(bounds);
    }
  );

  ipcMain.handle("close-app", () => {
    app.quit();
  });

  ipcMain.handle("set-always-on-top", (_event, enabled: boolean) => {
    mainWindow?.setAlwaysOnTop(enabled);
  });

  ipcMain.handle("set-opacity", (_event, opacity: number) => {
    if (!mainWindow) return;
    mainWindow.setOpacity(Math.max(0.1, Math.min(1.0, opacity)));
  });

  ipcMain.handle("get-cursor-window-point", () => {
    if (!mainWindow || mainWindow.isDestroyed()) {
      return { x: 0, y: 0 };
    }
    let point = screen.getCursorScreenPoint();
    try {
      const nativePoint = jsautogui.mouse.getPosition();
      if (Number.isFinite(nativePoint.x) && Number.isFinite(nativePoint.y)) {
        point = nativePoint;
      }
    } catch {
      // fall back to Electron cursor position
    }
    const bounds = mainWindow.getBounds();
    return { x: point.x - bounds.x, y: point.y - bounds.y };
  });

  ipcMain.handle("get-model-overrides", () => {
    try {
      const modelDictPath = path.resolve(process.cwd(), "model_dict.json");
      const raw = fs.readFileSync(modelDictPath, "utf-8");
      const modelDict = JSON.parse(raw) as Array<Record<string, unknown>>;
      const modelName = appConfig?.live2d_model_name;
      const matched = modelDict.find((m) => m.name === modelName);
      if (!matched) return {};

      const result: { kScale?: number; initialXshift?: number; initialYshift?: number } = {};
      if (typeof matched.kScale === "number") result.kScale = matched.kScale;
      if (typeof matched.initialXshift === "number") {
        result.initialXshift = matched.initialXshift;
      }
      if (typeof matched.initialYshift === "number") {
        result.initialYshift = matched.initialYshift;
      }
      return result;
    } catch {
      return {};
    }
  });

}

app.whenReady().then(() => {
  appConfig = loadConfigFromYaml();
  setupIPC();
  createWindow();
  createTray();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
