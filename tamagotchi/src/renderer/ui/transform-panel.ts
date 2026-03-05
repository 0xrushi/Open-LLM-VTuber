import type { Live2DRenderer } from "../live2d-renderer";
import type { AudioManager } from "../audio-manager";

/**
 * Panel with sliders to adjust the Live2D model's position, scale, rotation,
 * and window opacity.
 */
export class TransformPanel {
  private container: HTMLElement;
  private live2d: Live2DRenderer;
  private audio: AudioManager | null = null;

  constructor(live2d: Live2DRenderer, audio?: AudioManager) {
    this.live2d = live2d;
    this.audio = audio ?? null;

    this.container = document.createElement("div");
    this.container.id = "transform-panel";
    document.body.appendChild(this.container);

    this.render();
  }

  private render(): void {
    this.container.innerHTML = `
      <div class="transform-panel-inner">
        <div class="transform-header">Model Transform</div>

        <label class="transform-label">
          Scale
          <input type="range" id="tf-scale" min="5" max="200" value="100" step="1" />
          <span id="tf-scale-val">1.00</span>
        </label>

        <label class="transform-label">
          Rotation
          <input type="range" id="tf-rotation" min="-180" max="180" value="0" step="1" />
          <span id="tf-rotation-val">0°</span>
        </label>

        <label class="transform-label">
          X Offset
          <input type="range" id="tf-x" min="-500" max="500" value="0" step="1" />
          <span id="tf-x-val">0</span>
        </label>

        <label class="transform-label">
          Y Offset
          <input type="range" id="tf-y" min="-500" max="500" value="0" step="1" />
          <span id="tf-y-val">0</span>
        </label>

        <div class="transform-divider"></div>
        <div class="transform-header">Window</div>

        <label class="transform-label">
          Opacity
          <input type="range" id="tf-opacity" min="0" max="100" value="15" step="1" />
          <span id="tf-opacity-val">15%</span>
        </label>

        <div class="transform-divider"></div>
        <div class="transform-header">Audio</div>

        <label class="transform-label mic-select-label">
          Mic
          <select id="tf-mic-select">
            <option value="">Default</option>
          </select>
        </label>

        <button id="tf-reset" class="transform-reset-btn">Reset All</button>
      </div>
    `;

    const scaleSlider = this.container.querySelector("#tf-scale") as HTMLInputElement;
    const rotSlider = this.container.querySelector("#tf-rotation") as HTMLInputElement;
    const xSlider = this.container.querySelector("#tf-x") as HTMLInputElement;
    const ySlider = this.container.querySelector("#tf-y") as HTMLInputElement;
    const opacitySlider = this.container.querySelector("#tf-opacity") as HTMLInputElement;
    const scaleVal = this.container.querySelector("#tf-scale-val")!;
    const rotVal = this.container.querySelector("#tf-rotation-val")!;
    const xVal = this.container.querySelector("#tf-x-val")!;
    const yVal = this.container.querySelector("#tf-y-val")!;
    const opacityVal = this.container.querySelector("#tf-opacity-val")!;
    const resetBtn = this.container.querySelector("#tf-reset")!;

    let baseX = 0;
    let baseY = 0;
    let baseScale = 1;

    const syncFromModel = () => {
      const pos = this.live2d.getPosition();
      const scale = this.live2d.getScale();
      const rot = this.live2d.getRotation();
      baseX = pos.x;
      baseY = pos.y;
      baseScale = scale;
      scaleSlider.value = String(Math.round(scale * 100));
      scaleVal.textContent = scale.toFixed(2);
      rotSlider.value = String(Math.round(rot));
      rotVal.textContent = `${Math.round(rot)}°`;
      xSlider.value = "0";
      xVal.textContent = "0";
      ySlider.value = "0";
      yVal.textContent = "0";
    };

    setTimeout(syncFromModel, 500);

    // Re-sync whenever the Live2D model is (re)loaded
    this.live2d.onModelLoaded(() => {
      syncFromModel();
    });

    scaleSlider.addEventListener("input", () => {
      const scale = parseInt(scaleSlider.value) / 100;
      scaleVal.textContent = scale.toFixed(2);
      this.live2d.setScale(scale);
    });

    rotSlider.addEventListener("input", () => {
      const deg = parseInt(rotSlider.value);
      rotVal.textContent = `${deg}°`;
      this.live2d.setRotation(deg);
    });

    xSlider.addEventListener("input", () => {
      const dx = parseInt(xSlider.value);
      xVal.textContent = String(dx);
      const pos = this.live2d.getPosition();
      this.live2d.moveModel(baseX + dx - pos.x, 0);
    });

    ySlider.addEventListener("input", () => {
      const dy = parseInt(ySlider.value);
      yVal.textContent = String(dy);
      const pos = this.live2d.getPosition();
      this.live2d.moveModel(0, baseY + dy - pos.y);
    });

    const applyOpacity = (pct: number) => {
      const alpha = Math.max(0, Math.min(100, pct)) / 100;
      document.documentElement.style.setProperty(
        "--window-bg-opacity",
        String(alpha)
      );
    };

    opacitySlider.addEventListener("input", () => {
      const pct = parseInt(opacitySlider.value);
      opacityVal.textContent = `${pct}%`;
      applyOpacity(pct);
    });

    // Mic device selector
    const micSelect = this.container.querySelector("#tf-mic-select") as HTMLSelectElement;
    if (this.audio) {
      const audioRef = this.audio;
      const populateMicList = async () => {
        const devices = await audioRef.listMicDevices();
        const currentVal = micSelect.value;
        micSelect.innerHTML = '<option value="">Default</option>';
        for (const dev of devices) {
          const opt = document.createElement("option");
          opt.value = dev.deviceId;
          opt.textContent = dev.label || `Mic (${dev.deviceId.slice(0, 8)})`;
          micSelect.appendChild(opt);
        }
        // Restore selection if still available
        if (currentVal && [...micSelect.options].some((o) => o.value === currentVal)) {
          micSelect.value = currentVal;
        }
      };
      populateMicList();
      // Refresh device list when devices change (e.g. plug/unplug)
      navigator.mediaDevices.addEventListener("devicechange", populateMicList);

      micSelect.addEventListener("change", () => {
        audioRef.setMicDeviceId(micSelect.value || null);
      });
    }

    resetBtn.addEventListener("click", () => {
      syncFromModel();
      this.live2d.setScale(baseScale);
      this.live2d.setRotation(0);
      opacitySlider.value = "15";
      opacityVal.textContent = "15%";
      applyOpacity(15);
    });
  }

  setVisible(visible: boolean): void {
    this.container.classList.toggle("visible", visible);
  }
}
