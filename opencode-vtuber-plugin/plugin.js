import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PLUGIN_DIR = path.dirname(fileURLToPath(import.meta.url));
const PYTHON_CANDIDATES = [
  process.env.OPENCODE_VTUBER_PYTHON,
  path.join(PLUGIN_DIR, "..", ".venv", "bin", "python"),
  "python3",
];

function pickPython() {
  for (const candidate of PYTHON_CANDIDATES) {
    if (!candidate) {
      continue;
    }
    if (candidate.includes(path.sep) && fs.existsSync(candidate)) {
      return candidate;
    }
    if (!candidate.includes(path.sep)) {
      return candidate;
    }
  }
  return "python3";
}

function spawnScript(scriptName, payload) {
  const scriptPath = path.join(PLUGIN_DIR, "scripts", scriptName);
  const child = spawn(
    pickPython(),
    [scriptPath],
    {
      stdio: ["pipe", "ignore", "ignore"],
      detached: true,
      env: {
        ...process.env,
        OPENCODE_VTUBER_SKIP: "1",
      },
    },
  );

  if (payload) {
    child.stdin.write(`${JSON.stringify(payload)}\n`);
  }
  child.stdin.end();
  child.unref();
}

function summarizeChatParts(parts) {
  if (!Array.isArray(parts)) {
    return "";
  }
  const text = parts
    .map((part) => {
      if (typeof part === "string") {
        return part;
      }
      if (part && typeof part.text === "string") {
        return part.text;
      }
      if (part && typeof part.content === "string") {
        return part.content;
      }
      return "";
    })
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
  return text.slice(0, 500);
}

export const OpenCodeVtuberPlugin = async () => {
  if (process.env.OPENCODE_VTUBER_SKIP === "1") {
    return {};
  }

  return {
    "tool.execute.after": async (input, output) => {
      spawnScript("log_event.py", {
        hook_type: "tool.execute.after",
        tool_name: input.tool,
        tool_input: output.args ?? input.args ?? {},
        tool_result: String(output.output ?? "").slice(0, 400),
      });
    },

    "chat.message": async (_input, output) => {
      const message = summarizeChatParts(output.parts ?? []);
      if (!message) {
        return;
      }
      spawnScript("log_event.py", {
        hook_type: "chat.message",
        message,
      });
    },

    event: async ({ event }) => {
      if (event?.type !== "session.idle") {
        return;
      }
      spawnScript("run_pipeline.py", null);
    },
  };
};

export default OpenCodeVtuberPlugin;
