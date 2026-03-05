import { WebSocketClient } from "./websocket-client";
import { Live2DRenderer } from "./live2d-renderer";
import { AudioManager } from "./audio-manager";
import { ControlsIsland } from "./ui/controls-island";
import { ChatOverlay } from "./ui/chat-overlay";
import { ResizeHandles } from "./ui/resize-handles";
import { TransformPanel } from "./ui/transform-panel";

declare global {
  interface Window {
    electronAPI: {
      getConfig: () => Promise<{
        host: string;
        port: number;
        live2d_model_name: string;
        tamagotchi: {
          enabled: boolean;
          window_width: number;
          window_height: number;
          always_on_top: boolean;
          click_through: boolean;
          opacity: number;
        };
      }>;
      setClickThrough: (enabled: boolean) => Promise<void>;
      moveWindow: (deltaX: number, deltaY: number) => Promise<void>;
      resizeWindow: (bounds: {
        x: number;
        y: number;
        width: number;
        height: number;
      }) => Promise<void>;
      closeApp: () => Promise<void>;
      setAlwaysOnTop: (enabled: boolean) => Promise<void>;
      setOpacity: (opacity: number) => Promise<void>;
      onGlobalPointer: (
        callback: (windowX: number, windowY: number) => void
      ) => () => void;
      getModelOverrides: () => Promise<{
        kScale?: number;
        initialXshift?: number;
        initialYshift?: number;
      }>;
    };
  }
}

async function main() {
  console.log("[tamagotchi] starting...");

  const config = await window.electronAPI.getConfig();
  const modelOverrides = await window.electronAPI.getModelOverrides();
  console.log("[tamagotchi] config:", config);

  // 0.0.0.0 isn't reachable from browsers, use localhost instead
  const host = config.host === "0.0.0.0" ? "localhost" : config.host;
  const baseUrl = `http://${host}:${config.port}`;
  const wsUrl = `ws://${host}:${config.port}/client-ws`;

  // Status indicator
  const statusEl = document.getElementById("status-indicator")!;
  function setStatus(status: "connected" | "disconnected" | "reconnecting") {
    statusEl.className = `status-${status}`;
    statusEl.textContent =
      status === "connected"
        ? ""
        : status === "reconnecting"
          ? "Reconnecting..."
          : "Disconnected";
    console.log("[tamagotchi] status:", status);
  }

  // Initialize components
  console.log("[tamagotchi] initializing Live2D renderer...");
  const live2d = new Live2DRenderer("live2d-canvas", baseUrl);

  window.electronAPI.onGlobalPointer((windowX: number, windowY: number) => {
    live2d.focusFromWindowPoint(windowX, windowY);
  });
  const audio = new AudioManager(baseUrl);
  const wsClient = new WebSocketClient(wsUrl);
  const controls = new ControlsIsland(
    document.getElementById("controls-island")!
  );
  const chat = new ChatOverlay(document.getElementById("chat-overlay")!);
  new ResizeHandles();

  // Wire up WebSocket events
  wsClient.on("connected", () => {
    setStatus("connected");
    wsClient.send({ type: "request-init-config" });
  });

  wsClient.on("disconnected", () => setStatus("disconnected"));
  wsClient.on("reconnecting", () => setStatus("reconnecting"));

  wsClient.on("set-model-and-conf", async (data: Record<string, unknown>) => {
    console.log("[tamagotchi] set-model-and-conf received:", data);
    const modelInfo = data.model_info as Record<string, unknown> | undefined;
    if (modelInfo && modelInfo.url) {
      const url = modelInfo.url as string;
      console.log("[tamagotchi] loading model from:", url);
      await live2d.loadModel(url, {
        ...modelInfo,
        ...modelOverrides,
      });
    }
  });

  wsClient.on("full-text", (data: Record<string, unknown>) => {
    // full-text is used for status messages like "Thinking..." — skip those.
    // Actual AI response text comes via the audio message's display_text field.
    const text = data.text as string;
    console.log("[tamagotchi] full-text:", text);
  });

  wsClient.on("audio", async (data: Record<string, unknown>) => {
    console.log("[tamagotchi] audio message keys:", Object.keys(data));
    const audioBase64 = data.audio as string | null;
    const volumes = (data.volumes as number[]) || [];
    const sliceLength = (data.slice_length as number) || 20;
    const actions = data.actions as Record<string, unknown> | null;
    const displayText = data.display_text as Record<string, string> | null;

    // Show the actual response text in chat
    if (displayText && displayText.text) {
      chat.addMessage("ai", displayText.text);
    }

    // Notify backend that playback started
    wsClient.send({ type: "audio-play-start" });

    // Play expression/motion from actions
    if (actions && actions.expression_list) {
      const exprList = actions.expression_list as number[];
      if (exprList.length > 0) {
        live2d.setExpression(exprList[0]);
      }
    }

    // Play audio with lip sync if audio data exists
    if (audioBase64) {
      await audio.playBase64Audio(audioBase64, volumes, sliceLength, (volume: number) => {
        live2d.setMouthOpenness(volume);
      });
    }

    // Notify backend playback complete
    wsClient.send({ type: "frontend-playback-complete" });
  });

  wsClient.on("backend-synth-complete", () => {
    // Backend finished synthesizing all audio
  });

  // Controls: Mic toggle (always-on with server-side VAD)
  let micStreaming = false;
  controls.onMicToggle(async (active: boolean) => {
    if (active) {
      try {
        micStreaming = true;
        await audio.startMicCapture((audioData: Float32Array) => {
          if (micStreaming) {
            wsClient.send({
              type: "raw-audio-data",
              audio: Array.from(audioData),
            });
          }
        });
      } catch (err) {
        console.error("[tamagotchi] Mic capture failed:", err);
        micStreaming = false;
        controls.setMicActive(false);
      }
    } else {
      micStreaming = false;
      audio.stopMicCapture();
    }
  });

  // Handle server-side VAD control messages
  wsClient.on("control", (data: Record<string, unknown>) => {
    const text = data.text as string;
    if (text === "mic-audio-end") {
      // VAD detected end of speech — trigger conversation
      wsClient.send({ type: "mic-audio-end" });
    } else if (text === "interrupt") {
      // VAD detected new speech while AI is talking — interrupt
      audio.stopPlayback();
      live2d.setMouthOpenness(0);
      wsClient.send({ type: "interrupt-signal" });
    }
    const action = data.action as string;
    if (action === "clear-chat-history") {
      chat.clear();
    }
  });

  // Controls: Chat toggle
  controls.onChatToggle((visible: boolean) => {
    chat.setVisible(visible);
  });

  // Controls: Transform toggle
  const transformPanel = new TransformPanel(live2d, audio, wsClient);
  controls.onTransformToggle((visible: boolean) => {
    transformPanel.setVisible(visible);
  });

  // Wakeword status updates from server
  wsClient.on("wakeword-status", (data: Record<string, unknown>) => {
    const activated = data.activated as boolean;
    transformPanel.setWakewordStatus(activated);
  });

  // Chat: Send text
  chat.onSend((text: string) => {
    chat.addMessage("user", text);
    wsClient.send({ type: "text-input", text });
  });

  // Controls: Drag
  controls.onDrag((deltaX: number, deltaY: number) => {
    window.electronAPI.moveWindow(deltaX, deltaY);
  });

  // Controls: Close
  controls.onClose(() => {
    window.electronAPI.closeApp();
  });

  // Click-through is OFF by default so the window is always interactable.
  // Users can toggle it via a future settings button if needed.

  // Live2D tap interaction
  live2d.onTap(() => {
    wsClient.send({ type: "interrupt-signal" });
  });

  // Start connection
  wsClient.connect();

  // Heartbeat
  setInterval(() => {
    if (wsClient.isConnected()) {
      wsClient.send({ type: "heartbeat" });
    }
  }, 30000);
}

main().catch(console.error);
