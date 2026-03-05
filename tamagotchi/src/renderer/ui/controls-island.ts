type MicToggleCallback = (active: boolean) => void;
type ChatToggleCallback = (visible: boolean) => void;
type TransformToggleCallback = (visible: boolean) => void;
type DragCallback = (deltaX: number, deltaY: number) => void;
type CloseCallback = () => void;

/**
 * Floating controls island with mic, chat, transform, drag, and close buttons.
 */
export class ControlsIsland {
  private container: HTMLElement;
  private micBtn: Element | null = null;
  private micActive = false;
  private chatVisible = false;
  private transformVisible = false;
  private micCallbacks: MicToggleCallback[] = [];
  private chatCallbacks: ChatToggleCallback[] = [];
  private transformCallbacks: TransformToggleCallback[] = [];
  private dragCallbacks: DragCallback[] = [];
  private closeCallbacks: CloseCallback[] = [];

  constructor(container: HTMLElement) {
    this.container = container;
    this.render();
  }

  private render(): void {
    this.container.innerHTML = `
      <button class="control-btn" id="btn-mic" title="Toggle Microphone">
        <span class="icon">🎤</span>
        <span class="mic-indicator"></span>
      </button>
      <button class="control-btn" id="btn-chat" title="Toggle Chat">
        <span class="icon">💬</span>
      </button>
      <button class="control-btn" id="btn-transform" title="Model Transform">
        <span class="icon">⚙</span>
      </button>
      <button class="control-btn drag-handle" id="btn-drag" title="Drag Window">
        <span class="icon">✥</span>
      </button>
      <button class="control-btn" id="btn-close" title="Close">
        <span class="icon">✕</span>
      </button>
    `;

    // Mic button
    this.micBtn = this.container.querySelector("#btn-mic")!;
    this.micBtn.addEventListener("click", () => {
      this.micActive = !this.micActive;
      this.micBtn!.classList.toggle("active", this.micActive);
      for (const cb of this.micCallbacks) cb(this.micActive);
    });

    // Chat button
    const chatBtn = this.container.querySelector("#btn-chat")!;
    chatBtn.addEventListener("click", () => {
      this.chatVisible = !this.chatVisible;
      chatBtn.classList.toggle("active", this.chatVisible);
      for (const cb of this.chatCallbacks) cb(this.chatVisible);
    });

    // Transform button
    const transformBtn = this.container.querySelector("#btn-transform")!;
    transformBtn.addEventListener("click", () => {
      this.transformVisible = !this.transformVisible;
      transformBtn.classList.toggle("active", this.transformVisible);
      for (const cb of this.transformCallbacks) cb(this.transformVisible);
    });

    // Drag handle
    const dragBtn = this.container.querySelector("#btn-drag")!;
    let dragging = false;
    let lastX = 0;
    let lastY = 0;

    dragBtn.addEventListener("mousedown", (e: Event) => {
      const me = e as MouseEvent;
      dragging = true;
      lastX = me.screenX;
      lastY = me.screenY;
      me.preventDefault();
    });

    window.addEventListener("mousemove", (e: MouseEvent) => {
      if (!dragging) return;
      const deltaX = e.screenX - lastX;
      const deltaY = e.screenY - lastY;
      lastX = e.screenX;
      lastY = e.screenY;
      for (const cb of this.dragCallbacks) cb(deltaX, deltaY);
    });

    window.addEventListener("mouseup", () => {
      dragging = false;
    });

    // Close button
    const closeBtn = this.container.querySelector("#btn-close")!;
    closeBtn.addEventListener("click", () => {
      for (const cb of this.closeCallbacks) cb();
    });
  }

  onMicToggle(callback: MicToggleCallback): void {
    this.micCallbacks.push(callback);
  }

  onChatToggle(callback: ChatToggleCallback): void {
    this.chatCallbacks.push(callback);
  }

  onTransformToggle(callback: TransformToggleCallback): void {
    this.transformCallbacks.push(callback);
  }

  onDrag(callback: DragCallback): void {
    this.dragCallbacks.push(callback);
  }

  onClose(callback: CloseCallback): void {
    this.closeCallbacks.push(callback);
  }

  setMicActive(active: boolean): void {
    this.micActive = active;
    if (this.micBtn) {
      this.micBtn.classList.toggle("active", active);
    }
  }
}
