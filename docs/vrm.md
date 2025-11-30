# VRM Avatar Support (Experimental)

Open-LLM-VTuber now ships with a VRM player powered by [three.js](https://threejs.org/) and [`@pixiv/three-vrm`](https://www.npmjs.com/package/@pixiv/three-vrm).  
This viewer runs inside the same canvas that Live2D uses, so you can freely switch between 2D and 3D characters without changing the rest of your workflow.

## Requirements

- `three@^0.181` and `@pixiv/three-vrm@^3` are already listed in `package.json`.
- Any `.vrm` v0/v1 model that can be loaded by [`VRMLoaderPlugin`](https://github.com/pixiv/three-vrm).
- A place where the backend can serve the VRM file (for example `models/vrm/<name>.vrm`). You can also point to a CDN URL.

## Model configuration

The VRM viewer is enabled through `model_info` messages that come from the backend.  
To make a model render in 3D, add a new entry to `model_dict.json` (or wherever you build your model list) that sets `renderer: "vrm"`.  
When `renderer` is omitted, the UI also checks whether the URL ends with `.vrm`, so either approach works.

```jsonc
{
  "name": "vrm_mio",
  "description": "Sample VRM avatar",
  "renderer": "vrm",
  "url": "/vrm/VRM1_Constraint_Twist_Sample.vrm",
  "kScale": 1,
  "initialXshift": 0,
  "initialYshift": -1.2,
  "cameraPosition": [0, 1.35, 1.4],
  "cameraTarget": [0, 1.35, 0],
  "autoRotate": true,
  "backgroundColor": "#000000",
  "emotionMap": {},
  "tapMotions": {},
  "scrollToResize": false
}
```

### Field reference

| Field | Description |
| --- | --- |
| `renderer` | Set to `"vrm"` to force the viewer to use the VRM pipeline. If omitted, the frontend falls back to a file-extension check. |
| `url` | Absolute or relative path to your `.vrm` file. Relative paths are automatically prefixed with the backend `baseUrl`. |
| `kScale` | Uniform scale applied to the VRM scene. Defaults to `1`. |
| `initialXshift` / `initialYshift` | Translate the VRM scene along X/Y. Useful to keep models centered inside the viewport. |
| `cameraPosition` | Optional `[x, y, z]` tuple that controls the perspective camera. Defaults to `[0, 1.3, 1.2]`. |
| `cameraTarget` | Optional `[x, y, z]` tuple for the orbit-controls target. Defaults to `[0, 1.3, 0]`. |
| `autoRotate` | Enable/disable `OrbitControls.autoRotate`. Defaults to `true`. |
| `backgroundColor` | Provide a hex color (e.g., `"#101020"`) to render on a solid background. Leave empty for transparency so the desktop background is visible. |

> ℹ️ You can still keep `emotionMap`/`tapMotions` in place for compatibility—even though the VRM path does not use them yet.

Once the entry is added, set `live2d_model_name` in `conf.yaml` (or the character-specific YAML) to that model name.  
When the backend sends a `set-model-and-conf` message for the new model, the frontend will swap the Live2D renderer with the VRM viewer automatically.

## Tips

- You can host VRM files on CDNs such as jsDelivr or GitHub Pages. Just point the `url` directly to the remote asset.
- The viewer exposes orbit controls, so you can drag with the mouse to rotate the character in window mode. In pet mode, pointer events obey the existing “ignore mouse” toggle.
- Because the viewer runs on the same canvas area, existing subtitles, status widgets, and pet mode overlays still work.

If you run into issues, open the developer tools console—`VRMLoaderPlugin` will log detailed errors (missing textures, invalid VRM, etc.).  
Feel free to adapt the component further (custom lights, animations, blending with Live2D, etc.)!

## Remote motion API

The backend exposes a lightweight HTTP endpoint that lets you pose any humanoid bone in real time.  
Send a `POST` request to `/vrm/motion` with a JSON payload that describes each bone you want to update.

```jsonc
{
  "target_client_uid": null,             // Optional. When omitted, the pose is broadcast to all viewers.
  "bones": [
    {
      "name": "RightLowerArm",
      "rotation": { "x": 0, "y": 0, "z": 1.5707 }, // radians (Euler XYZ). Supply w for quaternions.
      "position": null
    },
    {
      "name": "LeftUpperArm",
      "rotation": { "x": 0.2, "y": 0, "z": 0 }
    }
  ]
}
```

- `rotation`: When a `w` component is provided it is treated as a quaternion. Otherwise the `x/y/z` values are interpreted as radians (XYZ Euler order).
- `position`: Optional absolute position override (in meters) for the selected bone.
- `target_client_uid`: Use the UID that the frontend logs on connect to drive a single avatar. Leave it empty to broadcast to all connected tabs.

The server immediately forwards the payload over `/client-ws` as a `vrm-motion` message, and the new renderer applies it frame-perfectly.  
This makes it easy to stream gestures from another process (e.g. motion capture) or script quick poses without touching the React layer.
