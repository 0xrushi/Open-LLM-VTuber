type Direction =
  | "n"
  | "s"
  | "e"
  | "w"
  | "ne"
  | "nw"
  | "se"
  | "sw";

/**
 * 8-directional invisible edge zones for window resizing via IPC.
 */
export class ResizeHandles {
  private readonly EDGE_SIZE = 6;

  constructor() {
    this.createHandles();
  }

  private createHandles(): void {
    const directions: Direction[] = [
      "n",
      "s",
      "e",
      "w",
      "ne",
      "nw",
      "se",
      "sw",
    ];

    for (const dir of directions) {
      const handle = document.createElement("div");
      handle.className = `resize-handle resize-${dir}`;
      handle.style.position = "fixed";
      handle.style.zIndex = "9999";

      this.positionHandle(handle, dir);
      this.attachDrag(handle, dir);

      document.body.appendChild(handle);
    }
  }

  private positionHandle(el: HTMLElement, dir: Direction): void {
    const s = this.EDGE_SIZE;

    switch (dir) {
      case "n":
        Object.assign(el.style, {
          top: "0",
          left: `${s}px`,
          right: `${s}px`,
          height: `${s}px`,
          cursor: "n-resize",
        });
        break;
      case "s":
        Object.assign(el.style, {
          bottom: "0",
          left: `${s}px`,
          right: `${s}px`,
          height: `${s}px`,
          cursor: "s-resize",
        });
        break;
      case "e":
        Object.assign(el.style, {
          top: `${s}px`,
          right: "0",
          bottom: `${s}px`,
          width: `${s}px`,
          cursor: "e-resize",
        });
        break;
      case "w":
        Object.assign(el.style, {
          top: `${s}px`,
          left: "0",
          bottom: `${s}px`,
          width: `${s}px`,
          cursor: "w-resize",
        });
        break;
      case "ne":
        Object.assign(el.style, {
          top: "0",
          right: "0",
          width: `${s}px`,
          height: `${s}px`,
          cursor: "ne-resize",
        });
        break;
      case "nw":
        Object.assign(el.style, {
          top: "0",
          left: "0",
          width: `${s}px`,
          height: `${s}px`,
          cursor: "nw-resize",
        });
        break;
      case "se":
        Object.assign(el.style, {
          bottom: "0",
          right: "0",
          width: `${s}px`,
          height: `${s}px`,
          cursor: "se-resize",
        });
        break;
      case "sw":
        Object.assign(el.style, {
          bottom: "0",
          left: "0",
          width: `${s}px`,
          height: `${s}px`,
          cursor: "sw-resize",
        });
        break;
    }
  }

  private attachDrag(handle: HTMLElement, dir: Direction): void {
    let startX = 0;
    let startY = 0;
    let startBounds = { x: 0, y: 0, width: 0, height: 0 };

    handle.addEventListener("mousedown", (e: MouseEvent) => {
      e.preventDefault();
      startX = e.screenX;
      startY = e.screenY;
      startBounds = {
        x: window.screenX,
        y: window.screenY,
        width: window.outerWidth,
        height: window.outerHeight,
      };

      const onMove = (me: MouseEvent) => {
        const dx = me.screenX - startX;
        const dy = me.screenY - startY;
        const newBounds = { ...startBounds };

        if (dir.includes("e")) newBounds.width += dx;
        if (dir.includes("w")) {
          newBounds.x += dx;
          newBounds.width -= dx;
        }
        if (dir.includes("s")) newBounds.height += dy;
        if (dir.includes("n")) {
          newBounds.y += dy;
          newBounds.height -= dy;
        }

        // Enforce minimum size
        newBounds.width = Math.max(200, newBounds.width);
        newBounds.height = Math.max(200, newBounds.height);

        window.electronAPI?.resizeWindow(newBounds);
      };

      const onUp = () => {
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
      };

      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    });

  }
}
