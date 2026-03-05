type SendCallback = (text: string) => void;

/**
 * Slide-in chat panel with message history and text input.
 */
export class ChatOverlay {
  private container: HTMLElement;
  private messagesEl!: HTMLElement;
  private inputEl!: HTMLInputElement;
  private sendCallbacks: SendCallback[] = [];

  constructor(container: HTMLElement) {
    this.container = container;
    this.render();
  }

  private render(): void {
    this.container.innerHTML = `
      <div class="chat-panel">
        <div class="chat-messages" id="chat-messages"></div>
        <div class="chat-input-row">
          <input type="text" id="chat-input" placeholder="Type a message..." />
          <button id="chat-send">Send</button>
        </div>
      </div>
    `;

    this.messagesEl = this.container.querySelector("#chat-messages")!;
    this.inputEl = this.container.querySelector("#chat-input") as HTMLInputElement;
    const sendBtn = this.container.querySelector("#chat-send")!;

    const doSend = () => {
      const text = this.inputEl.value.trim();
      if (!text) return;
      this.inputEl.value = "";
      for (const cb of this.sendCallbacks) cb(text);
    };

    sendBtn.addEventListener("click", doSend);
    this.inputEl.addEventListener("keydown", (e: KeyboardEvent) => {
      if (e.key === "Enter") doSend();
    });

  }

  addMessage(role: "user" | "ai", text: string): void {
    const msgEl = document.createElement("div");
    msgEl.className = `chat-message chat-message-${role}`;
    msgEl.textContent = text;
    this.messagesEl.appendChild(msgEl);
    this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
  }

  clear(): void {
    this.messagesEl.innerHTML = "";
  }

  setVisible(visible: boolean): void {
    this.container.classList.toggle("visible", visible);
  }

  onSend(callback: SendCallback): void {
    this.sendCallbacks.push(callback);
  }
}
