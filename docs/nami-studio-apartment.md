# Nami Studio Apartment Scene

The `nami_byKitzoomer` VRM character can load the built-in `nami_studio_apartment` scene preset.

## Test The Scene

Start the backend:

```bash
uv run run_server.py
```

Start the web frontend:

```bash
cd Open-LLM-VTuber-Web
npm run dev:web
```

Select the `nami_byKitzoomer` character. The scene registry is exposed in DevTools:

```js
window.__AI_SCENE_REGISTRY__
```

The visual scene is procedural Three.js geometry. Interactable objects keep stable root names such as `CHAIR_Desk_01`, but most roots are composed groups with child meshes for details like legs, handles, cushions, doors, pillows, lantern glass, fruit, map rolls, and nautical props.

The scene uses bevelled/rounded box geometry and procedural materials for a less placeholder-like look:

- Wood grain generated with `CanvasTexture`.
- Woven fabric texture for cushions, blankets, pillows, and upholstery.
- Parchment map texture with drawn coastline-like strokes.
- Metallic brass materials for handles, compass, telescope, and lantern.
- Translucent glass material for the window, compass glass, telescope lens, and lantern.
- Floor plank seams, wall trim, sunset sun, and ocean glints.
- Premium staging details including layered rugs, ceiling beams, curtain folds, backsplash tiles, a hanging lantern, scattered coins, bottles, bedding runners, sofa throw fabric, and wall navigation art.
- Small props are built as composed meshes instead of single boxes where practical: sextant arcs, book covers/pages, coin jar glass and lid, plates/cups, bottle clusters, and utensil pieces.
- The renderer uses ACES filmic tone mapping, warmer exposure for this scene preset, soft shadow maps, and higher-resolution environment shadows.

These assets are still procedural placeholders. For production-quality realism, replace the grouped primitives with authored GLB assets that preserve the same root object IDs and registry metadata.

## Sit Commands

The frontend intercepts simple local scene commands and does not send them to the LLM backend.

Supported examples:

```txt
please sit on the chair
sit on the desk chair
sit on the living chair
sit on the sofa
sit on the bed
stand up
get up
walk to the kitchen drawer
go to the sofa
inspect the world map
read the weather book
open the lower cupboard
close the lower cupboard
open the treasure chest
pick up the compass
pick up the telescope
look out the ocean window
call the Den Den Mushi
toggle the lantern
```

Direct DevTools test:

```js
window.vtuberPose.sit("CHAIR_Desk_01")
window.vtuberPose.stand()
window.vtuberPose.action("moveTo", "DRAWER_Kitchen_01")
window.vtuberPose.action("open", "CUPBOARD_Kitchen_Lower_01")
window.vtuberPose.action("pickUp", "PROP_Compass_01")
```

## How Sitting Works

Walking and sitting use Mixamo FBX assets at:

```txt
/models/animations/WalkingAnimation.fbx
/models/animations/SittingTalkingFromMixamo.fbx
```

For VRM avatars, the animation is retargeted through the VRM-specific Mixamo path and position tracks are ignored so the FBX cannot drag the avatar root below the chair.

After the animation runs, a lightweight kinematic contact correction runs every frame:

- It reads the target object's `interactionPoints.sit`.
- It measures the avatar hips bone world position.
- It adjusts the avatar root Y so the hips stay aligned to the seat height.
- It keeps root X/Z and yaw locked to the selected seat.
- It treats the Mixamo sitting clip as a one-shot transition and clamps the final seated frame so the clip does not loop back into a stand/sit transition.
- It checks both foot bones and raises the root if either foot penetrates the floor.
- It lazy-loads Rapier 3D on first sit and uses a small seated physics harness: fixed floor and chair colliders plus a damped dynamic pelvis body. The avatar root follows the solved pelvis height instead of only trusting the authored animation.

This is not a fully uncontrolled ragdoll. It is a physics-assisted seated controller. That is intentional: a fully dynamic ragdoll will collapse unless every major bone has tuned masses, colliders, limits, motors, and character-controller recovery. If later work needs hands-on-armrests or feet pinned to exact floor targets, add foot and hand interaction points to the registry and extend the same correction layer with limb constraints.

`stand up` clears the seated contact correction, stops the sitting animation, moves the avatar to the seated object's `approach` point, resets bones, and resumes idle.

## Common Actions

Common object actions use the registry and object names:

- `moveTo`: walks to `interactionPoints.approach`, faces `interactionPoints.lookAt`, then returns to idle.
- `inspect`, `read`, `lookOut`, `lookThrough`, `call`: walks to the object and focuses the camera on `lookAt`.
- `open`, `close`: walks to the object and applies a simple transform to drawers, cupboards, wardrobe, or chest.
- `pickUp`: walks to the object and hides the prop as a temporary pickup/inventory placeholder.
- `toggleLight`: walks to the lantern and toggles the lantern light intensity.

These are intentionally local scene actions. They do not yet do hand IK, inventory state, pathfinding around obstacles, or physical door hinges.

## Tuning

If a seat looks too high or low, adjust the object's `interactionPoints.sit[1]` in:

```txt
Open-LLM-VTuber-Web/src/renderer/src/components/canvas/nami-studio-scene.ts
```

Chair objects currently use IDs such as:

```txt
CHAIR_Desk_01
CHAIR_Living_01
SOFA_Living_01
BED_Main_01
```
