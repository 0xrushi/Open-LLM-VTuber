# Adding New Characters and 3D Models

This project supports two main avatar types:

- Live2D models (`.model3.json`)
- 3D models (VRM or GLB/GLTF) driven by the `VrmViewer`

This guide explains which files to touch when adding a new character or animation model.

---

## 1. Add a New 3D Avatar (VRM or GLB/GLTF)

### Step 1: Put the model file in the served `models` folder

The backend serves models from `frontend/models` via the `/models` URL.

1. Copy your model file to:
   - `frontend/models/YourModel.vrm`
   - or `frontend/models/YourModel.glb`
2. The file will then be reachable from the frontend as:
   - `/models/YourModel.vrm`
   - `/models/YourModel.glb`

### Step 2: Register the model in `model_dict.json`

File: `model_dict.json`

Add a new entry following the existing VRM/GLB examples:

```jsonc
{
  "name": "my_3d_avatar",
  "description": "My custom 3D character",
  "renderer": "vrm",              // keep "vrm" for VRM/GLB pipeline
  "url": "/models/YourModel.vrm", // or .glb / .gltf
  "kScale": 1,
  "initialXshift": 0,
  "initialYshift": 0,
  "cameraPosition": [0, 1.3, 1.8],
  "cameraTarget": [0, 1.3, 0],
  "autoRotate": true,
  "emotionMap": {},
  "tapMotions": {}
}
```

Important:

- `name` is the ID the rest of the config uses.
- `renderer` should be `"vrm"` for both VRM and GLB models so the Three.js/VRM viewer is used.
- `url` must start with `/models/` and match the filename in `frontend/models`.

### Step 3: Create a character config YAML

File: `characters/my_3d_avatar.yaml`

Create a minimal config that points to the same `name` you added in `model_dict.json`:

```yaml
character_config:
  conf_name: 'my_3d_avatar'
  conf_uid: 'my_3d_avatar_001'
  live2d_model_name: 'my_3d_avatar'  # must match model_dict.json "name"
  character_name: 'My Avatar'
  avatar: ''       # optional PNG in avatars/ if you want a portrait
  human_name: 'Human'

  persona_prompt: |
    You are My Avatar, a VTuber assistant.
```

This makes the model selectable as a “character” in the app.

### Step 4: (Optional) Make it the default character

File: `conf.yaml` → `character_config`

Update the default character to use your new model:

```yaml
character_config:
  conf_name: 'my_3d_avatar'
  conf_uid: 'my_3d_avatar_001'
  live2d_model_name: 'my_3d_avatar'
  character_name: 'My Avatar'
  avatar: ''   # optional portrait in avatars/
  human_name: 'Human'
```

Restart the backend after changing `conf.yaml` so it reloads the config.

---

## 2. Add a New Live2D Model

Live2D models use the classic Live2D pipeline instead of the 3D viewer.

### Step 1: Place the Live2D runtime files

1. Copy your Live2D model folder into:
   - `live2d-models/YourModel/runtime/...`
2. You should have a `.model3.json` file in that folder.

### Step 2: Register in `model_dict.json`

Add a new Live2D entry (no `renderer` field required):

```jsonc
{
  "name": "my_live2d",
  "description": "My Live2D model",
  "url": "/live2d-models/YourModel/runtime/YourModel.model3.json",
  "kScale": 0.5,
  "initialXshift": 0,
  "initialYshift": 0,
  "kXOffset": 1150,
  "idleMotionGroupName": "Idle",
  "emotionMap": {},
  "tapMotions": {}
}
```

### Step 3: Character YAML and default character

Same pattern as the 3D avatar:

- Create `characters/my_live2d.yaml` with `live2d_model_name: 'my_live2d'`.
- Optionally set `live2d_model_name` and `conf_name` to `my_live2d` in `conf.yaml` to make it default.

---

## 3. Add / Use VRMA Animation Clips

The VRM viewer can play VRMA (VRM animation) clips on top of a loaded VRM avatar.

### Option A: Upload VRMA at runtime (no code change)

- In the UI overlay on the 3D canvas, use the **“Upload .vrma”** button.
- This uses `handleVrmaUpload` in:
  - `Open-LLM-VTuber-Web/src/renderer/src/components/canvas/vrm-viewer.tsx`
- It loads the selected `.vrma` file, retargets tracks onto the current VRM humanoid, and plays it.

You only need a `.vrma` file; no code or config changes.

### Option B: Hard‑code a default VRMA clip

1. Place your VRMA file in `frontend/models/MyAnim.vrma`.
2. Update the hardcoded path in `VrmViewer` (double‑click handler):

File: `Open-LLM-VTuber-Web/src/renderer/src/components/canvas/vrm-viewer.tsx`

```ts
const handleDoubleClick = () => {
  console.log("Double click detected! Playing MyAnim...");
  playVrmaFromUrl("/models/MyAnim.vrma");
};
```

Now double‑clicking the 3D canvas will play your default animation on the current VRM avatar.

Notes:

- VRMA playback only works on VRM avatars (not on plain GLB models).
- Video‑driven pose (MediaPipe / Kalidokit) is also VRM‑only; for GLB avatars the video upload shows an error instead of applying broken motion.

---

## 4. Quick Checklist

**New 3D avatar (VRM/GLB):**

- [ ] Copy model to `frontend/models/YourModel.vrm` or `.glb`
- [ ] Add entry in `model_dict.json` with `"renderer": "vrm"` and `"url": "/models/YourModel.vrm"` (or `.glb`)
- [ ] Create `characters/<name>.yaml` with `live2d_model_name` matching the model `name`
- [ ] (Optional) Point `conf.yaml` → `character_config` to your new `conf_name` and `live2d_model_name`

**New Live2D model:**

- [ ] Copy model folder under `live2d-models/...` with a `.model3.json`
- [ ] Add entry in `model_dict.json` with `url` under `/live2d-models/...`
- [ ] Create `characters/<name>.yaml`
- [ ] (Optional) Update `conf.yaml` defaults

**New VRMA animation:**

- [ ] Put `.vrma` in `frontend/models`
- [ ] Either upload via the “Upload .vrma” button at runtime,
  or update `handleDoubleClick` in `vrm-viewer.tsx` to use your file.

