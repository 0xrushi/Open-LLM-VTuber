const { MakerSquirrel } = require("@electron-forge/maker-squirrel");
const { MakerZIP } = require("@electron-forge/maker-zip");
const { MakerDeb } = require("@electron-forge/maker-deb");
const { VitePlugin } = require("@electron-forge/plugin-vite");

module.exports = {
  packagerConfig: {
    asar: true,
    name: "Open-LLM-VTuber-Pet",
  },
  makers: [
    new MakerSquirrel({}),
    new MakerZIP({}, ["darwin"]),
    new MakerDeb({}),
  ],
  plugins: [
    new VitePlugin({
      build: [
        {
          entry: "src/main/main.ts",
          config: "vite.main.config.mjs",
          target: "main",
        },
        {
          entry: "src/main/preload.ts",
          config: "vite.preload.config.mjs",
          target: "preload",
        },
      ],
      renderer: [
        {
          name: "main_window",
          config: "vite.renderer.config.mjs",
        },
      ],
    }),
  ],
};
