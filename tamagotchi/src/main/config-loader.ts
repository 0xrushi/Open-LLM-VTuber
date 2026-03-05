import * as fs from "fs";
import * as path from "path";
import * as yaml from "js-yaml";

export interface TamagotchiConfig {
  enabled: boolean;
  window_width: number;
  window_height: number;
  always_on_top: boolean;
  click_through: boolean;
  opacity: number;
}

export interface AppConfig {
  host: string;
  port: number;
  live2d_model_name: string;
  tamagotchi: TamagotchiConfig;
}

const DEFAULT_CONFIG: AppConfig = {
  host: "localhost",
  port: 12393,
  live2d_model_name: "mao_pro",
  tamagotchi: {
    enabled: false,
    window_width: 400,
    window_height: 600,
    always_on_top: true,
    click_through: true,
    opacity: 1.0,
  },
};

/**
 * Load configuration from ../conf.yaml relative to the app root,
 * or fall back to fetching from the backend API.
 */
export function loadConfigFromYaml(): AppConfig {
  const confPaths = [
    path.resolve(process.cwd(), "conf.yaml"),
    path.resolve(__dirname, "..", "..", "..", "conf.yaml"),
    path.resolve(__dirname, "..", "..", "conf.yaml"),
  ];

  for (const confPath of confPaths) {
    if (fs.existsSync(confPath)) {
      try {
        const raw = fs.readFileSync(confPath, "utf-8");
        const parsed = yaml.load(raw) as Record<string, unknown>;

        const system = (parsed.system_config as Record<string, unknown>) || {};
        const character =
          (parsed.character_config as Record<string, unknown>) || {};
        const tamagotchi =
          (parsed.tamagotchi_config as Record<string, TamagotchiConfig>) || {};

        return {
          host: (system.host as string) || DEFAULT_CONFIG.host,
          port: (system.port as number) || DEFAULT_CONFIG.port,
          live2d_model_name:
            (character.live2d_model_name as string) ||
            DEFAULT_CONFIG.live2d_model_name,
          tamagotchi: {
            ...DEFAULT_CONFIG.tamagotchi,
            ...(tamagotchi as unknown as Partial<TamagotchiConfig>),
          },
        };
      } catch {
        console.warn(`Failed to parse ${confPath}, using defaults`);
      }
    }
  }

  console.warn("conf.yaml not found, using default configuration");
  return DEFAULT_CONFIG;
}

/**
 * Load/save window position state.
 */
const STATE_FILE = path.resolve(
  process.env.APPDATA ||
    process.env.HOME + "/.config" ||
    "/tmp",
  "open-llm-vtuber-pet",
  "window-state.json"
);

export interface WindowState {
  x?: number;
  y?: number;
  width: number;
  height: number;
}

export function loadWindowState(defaults: {
  width: number;
  height: number;
}): WindowState {
  try {
    if (fs.existsSync(STATE_FILE)) {
      return JSON.parse(fs.readFileSync(STATE_FILE, "utf-8"));
    }
  } catch {
    // ignore
  }
  return { width: defaults.width, height: defaults.height };
}

export function saveWindowState(state: WindowState): void {
  try {
    const dir = path.dirname(STATE_FILE);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    fs.writeFileSync(STATE_FILE, JSON.stringify(state));
  } catch {
    // ignore
  }
}
