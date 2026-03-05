// pixi.js and pixi-live2d-display are loaded via CDN <script> tags
// They expose PIXI globally, with Live2DModel at PIXI.live2d.Live2DModel
declare const PIXI: any;

type TapCallback = () => void;

/**
 * Renders Live2D models on a transparent PixiJS canvas.
 */
export class Live2DRenderer {
  private app: any;
  private model: any = null;
  private baseUrl: string;
  private canvas: HTMLCanvasElement;
  private modelDefaultScale = 1;
  private targetScale = 1;
  private modelInitialXShift = 0;
  private modelInitialYShift = 0;
  private tapCallbacks: TapCallback[] = [];
  private modelLoadedCallbacks: (() => void)[] = [];
  private _currentModelUrl: string | null = null;
  private _loadingUrl: string | null = null;
  private _mouthValue = 0;
  private _lipSyncTickerFn: (() => void) | null = null;

  constructor(canvasId: string, baseUrl: string) {
    this.baseUrl = baseUrl;

    this.canvas = document.getElementById(canvasId) as HTMLCanvasElement;

    this.app = new PIXI.Application({
      view: this.canvas,
      backgroundAlpha: 0,
      resizeTo: window,
      antialias: true,
    });

    // Mouse tracking for eye follow
    window.addEventListener("pointermove", (e: PointerEvent) => {
      const rect = this.canvas.getBoundingClientRect();
      this.focusFromCanvasPoint(e.clientX - rect.left, e.clientY - rect.top);
    });

    // Handle window resize
    window.addEventListener("resize", () => {
      if (this.model) {
        this.fitModel();
      }
    });
  }

  private focusFromCanvasPoint(localX: number, localY: number): void {
    if (!this.model) return;
    this.model.focus(localX, localY);
  }

  onModelLoaded(callback: () => void): void {
    this.modelLoadedCallbacks.push(callback);
  }

  focusFromWindowPoint(windowX: number, windowY: number): void {
    this.focusFromCanvasPoint(windowX, windowY);
  }

  async loadModel(
    modelUrl: string,
    modelInfo: Record<string, unknown>
  ): Promise<void> {
    // Build full URL
    let fullUrl: string;
    if (modelUrl.startsWith("http")) {
      fullUrl = modelUrl;
    } else {
      const cleanPath = modelUrl.startsWith("/") ? modelUrl.slice(1) : modelUrl;
      fullUrl = `${this.baseUrl}/${cleanPath}`;
    }

    // Skip if same model is already loaded or currently loading
    if ((this._currentModelUrl === fullUrl && this.model) || this._loadingUrl === fullUrl) {
      return;
    }

    // Clean up existing model and lip sync ticker
    this._cleanup();
    this._loadingUrl = fullUrl;

    const Live2DModel = PIXI.live2d.Live2DModel;

    try {
      const newModel = await Live2DModel.from(fullUrl);

      // Check if a different load was triggered while we were loading
      if (this._loadingUrl !== fullUrl) {
        newModel.destroy();
        return;
      }

      // Clean up again in case another load snuck in
      this._cleanup();
      this.model = newModel;
      this._currentModelUrl = fullUrl;
      this._loadingUrl = null;

      // Apply scale and offset from model_info
      const parsedScale = Number(modelInfo.kScale);
      this.modelDefaultScale = Number.isFinite(parsedScale) ? parsedScale : 1.0;
      this.targetScale = this.modelDefaultScale;
      console.log("[live2d] kScale from modelInfo:", modelInfo.kScale, "-> modelDefaultScale:", this.modelDefaultScale);
      this.modelInitialXShift =
        typeof modelInfo.initialXshift === "number" ? modelInfo.initialXshift : 0;
      this.modelInitialYShift =
        typeof modelInfo.initialYshift === "number" ? modelInfo.initialYshift : 0;

      this.model.scale.set(this.modelDefaultScale);
      this.model.anchor.set(0.5, 0.5);

      // Tap interaction
      this.model.on("hit", (_hitAreas: string[]) => {
        for (const cb of this.tapCallbacks) {
          cb();
        }
      });

      this.app.stage.addChild(this.model);

      this.fitModel();
      this.model.scale.set(this.modelDefaultScale);
      const loadedModel = this.model;
      setTimeout(() => {
        if (this.model === loadedModel) {
          this.model.scale.set(this.modelDefaultScale);
        }
      }, 200);

      // Initialize lip sync after model is on stage
      this._initLipSync();

      // Notify listeners that a model has been loaded (slight delay for pixi to settle)
      setTimeout(() => {
        for (const cb of this.modelLoadedCallbacks) {
          cb();
        }
      }, 300);
    } catch (err) {
      console.error("Failed to load Live2D model:", err);
      this._loadingUrl = null;
    }
  }

  private _cleanup(): void {
    // Remove old lip sync ticker
    if (this._lipSyncTickerFn) {
      PIXI.Ticker.shared.remove(this._lipSyncTickerFn);
      this._lipSyncTickerFn = null;
    }

    // Remove old model
    if (this.model) {
      this.app.stage.removeChild(this.model);
      this.model.destroy();
      this.model = null;
    }

    this._currentModelUrl = null;
    // Don't clear _loadingUrl here — it's used to guard concurrent loads
  }

  private fitModel(): void {
    if (!this.model) return;

    const { width, height } = this.app.screen;
    this.model.x = width / 2 + this.modelInitialXShift;
    this.model.y = height / 2 + this.modelInitialYShift;
  }

  setExpression(expressionIndex: number): void {
    if (!this.model) return;
    try {
      this.model.expression(expressionIndex);
    } catch (err) {
      console.warn("Failed to set expression:", expressionIndex, err);
    }
  }

  /**
   * Hook into PIXI ticker to apply mouth value every frame,
   * after the motion manager runs, so it doesn't get overwritten.
   */
  private _initLipSync(): void {
    if (!this.model) return;

    this._lipSyncTickerFn = () => {
      if (!this.model || !this.model.internalModel) return;

      if (Math.abs(this.model.scale.x - this.targetScale) > 0.0001) {
        this.model.scale.set(this.targetScale);
      }

      const coreModel = this.model.internalModel.coreModel;
      if (!coreModel) return;

      if (typeof coreModel.setParamFloat === "function") {
        coreModel.setParamFloat("PARAM_MOUTH_OPEN_Y", this._mouthValue);
      } else if (typeof coreModel.setParameterValueById === "function") {
        try {
          coreModel.setParameterValueById("ParamMouthOpenY", this._mouthValue);
        } catch {
          try {
            coreModel.setParameterValueById("PARAM_MOUTH_OPEN_Y", this._mouthValue);
          } catch {
            // not supported
          }
        }
      }
    };

    PIXI.Ticker.shared.add(this._lipSyncTickerFn);
  }

  setMouthOpenness(value: number): void {
    this._mouthValue = Math.min(value, 1.0);
  }

  moveModel(dx: number, dy: number): void {
    if (!this.model) return;
    this.model.x += dx;
    this.model.y += dy;
  }

  setScale(scale: number): void {
    if (!this.model) return;
    this.targetScale = Math.max(0.05, scale);
    this.model.scale.set(this.targetScale);
  }

  getScale(): number {
    return this.model ? this.targetScale : 1;
  }

  setRotation(degrees: number): void {
    if (!this.model) return;
    this.model.rotation = (degrees * Math.PI) / 180;
  }

  getRotation(): number {
    if (!this.model) return 0;
    return (this.model.rotation * 180) / Math.PI;
  }

  getPosition(): { x: number; y: number } {
    if (!this.model) return { x: 0, y: 0 };
    return { x: this.model.x, y: this.model.y };
  }

  onTap(callback: TapCallback): void {
    this.tapCallbacks.push(callback);
  }
}
