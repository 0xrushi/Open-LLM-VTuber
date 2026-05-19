import './styles.css';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { TransformControls } from 'three/examples/jsm/controls/TransformControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';
import { GLTFExporter } from 'three/examples/jsm/exporters/GLTFExporter.js';
import { ObjectControls } from 'threejs-object-controls';
import {
  LOCATION_STORAGE_KEY,
  applySavedLocations,
  createConfigPayload,
  createLocationsPayload,
  escapeHtml,
  makeDefaultMeta,
  normalizeName,
  num,
  round3,
  uniqueId,
} from './editor-state.js';

const canvas = document.querySelector('#viewport');
const statusEl = document.querySelector('#status');
const assetLibraryEl = document.querySelector('#assetLibrary');
const assetSearchEl = document.querySelector('#assetSearch');
const objectListEl = document.querySelector('#objectList');
const markerListEl = document.querySelector('#markerList');
const inspectorEl = document.querySelector('#inspector');
const emptyStateEl = document.querySelector('#emptyState');

const fields = {
  name: document.querySelector('#nameInput'),
  type: document.querySelector('#typeInput'),
  zone: document.querySelector('#zoneInput'),
  humanName: document.querySelector('#humanNameInput'),
  actions: document.querySelector('#actionsInput'),
  posX: document.querySelector('#posX'),
  posY: document.querySelector('#posY'),
  posZ: document.querySelector('#posZ'),
  rotX: document.querySelector('#rotX'),
  rotY: document.querySelector('#rotY'),
  rotZ: document.querySelector('#rotZ'),
  scaleX: document.querySelector('#scaleX'),
  scaleY: document.querySelector('#scaleY'),
  scaleZ: document.querySelector('#scaleZ'),
  color: document.querySelector('#colorInput'),
  sceneId: document.querySelector('#sceneIdInput'),
  displayName: document.querySelector('#displayNameInput'),
  roomWidth: document.querySelector('#roomWidthInput'),
  roomDepth: document.querySelector('#roomDepthInput'),
  roomHeight: document.querySelector('#roomHeightInput'),
  floorColor: document.querySelector('#floorColorInput'),
  wallColor: document.querySelector('#wallColorInput'),
};

window.addEventListener('error', (event) => {
  setStatus(`Error: ${event.message}`);
});

window.addEventListener('unhandledrejection', (event) => {
  setStatus(`Error: ${event.reason?.message ?? event.reason}`);
});

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setClearColor(0x111313);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.shadowMap.enabled = true;

const scene = new THREE.Scene();
scene.name = 'EditableEnvironment';
scene.background = new THREE.Color(0x111313);

const camera = new THREE.PerspectiveCamera(55, 1, 0.01, 500);
camera.position.set(5.5, 4.2, 7.5);

const orbit = new OrbitControls(camera, renderer.domElement);
orbit.target.set(0, 0.8, 0);
orbit.enableDamping = true;

const transform = new TransformControls(camera, renderer.domElement);
let transformInteracting = false;
transform.addEventListener('dragging-changed', (event) => {
  orbit.enabled = !event.value;
});
transform.addEventListener('mouseDown', () => {
  transformInteracting = true;
});
transform.addEventListener('mouseUp', () => {
  transformInteracting = false;
});
transform.addEventListener('objectChange', () => {
  syncInspectorFromSelection();
  renderLists();
});
transform.setSize(1.25);
transform.setSpace('world');
transform.showX = true;
transform.showY = true;
transform.showZ = true;
const transformHelper = transform.getHelper();
transformHelper.name = 'EditorTransformControlsHelper';
scene.add(transformHelper);

const objectControlsDummy = new THREE.Group();
const objectControls = new ObjectControls(camera, renderer.domElement, objectControlsDummy);
objectControls.setRotationSpeed(0.035);
objectControls.setRotationSpeedTouchDevices(0.035);
objectControls.enableHorizontalRotation();
objectControls.enableVerticalRotation();
objectControls.disableZoom();
let activeControlMode = 'translate';

const grid = new THREE.GridHelper(20, 40, 0x6d716e, 0x2d302e);
grid.name = 'EditorGrid';
scene.add(grid);

const floorPlane = new THREE.Mesh(
  new THREE.PlaneGeometry(20, 20),
  new THREE.MeshBasicMaterial({ visible: false }),
);
floorPlane.name = 'EditorFloorPickPlane';
floorPlane.rotation.x = -Math.PI / 2;
scene.add(floorPlane);

const ambient = new THREE.HemisphereLight(0xffffff, 0x304050, 1.8);
scene.add(ambient);
const key = new THREE.DirectionalLight(0xfff1d0, 2.5);
key.position.set(4, 6, 3);
key.castShadow = true;
scene.add(key);

const dracoLoader = new DRACOLoader();
dracoLoader.setDecoderPath('/draco/gltf/');
dracoLoader.setDecoderConfig({ type: 'wasm' });

const loader = new GLTFLoader();
loader.setDRACOLoader(dracoLoader);
const textureLoader = new THREE.TextureLoader();
const exporter = new GLTFExporter();
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
const roots = [];
let projectAssets = [];
let selected = null;
let selectedMarker = null;
const labelSprites = new Map();
let pickStart = null;
let objectDrag = null;
const dragPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
const roomState = {
  width: 8,
  depth: 6,
  height: 3,
  floorColor: '#c99a68',
  wallColor: '#3d3a4d',
  floorTexture: null,
  wallTexture: null,
};

const roomGroup = new THREE.Group();
roomGroup.name = 'ROOM_Block_01';
roomGroup.userData.editorRoom = true;
scene.add(roomGroup);
const roomMeshes = createRoomMeshes();
updateRoomBlock();

function setStatus(text) {
  statusEl.textContent = text;
}

function selectableRoot(object) {
  let current = object;
  while (current) {
    if (roots.includes(current) || current.userData.markerFor) return current;
    current = current.parent;
  }
  return null;
}

function createRoomMaterial(name, color) {
  const mat = new THREE.MeshStandardMaterial({
    name,
    color,
    roughness: 0.78,
    metalness: 0.02,
  });
  return mat;
}

function createRoomMeshes() {
  const floor = new THREE.Mesh(
    new THREE.BoxGeometry(1, 0.12, 1),
    createRoomMaterial('MAT_Room_Floor', roomState.floorColor),
  );
  floor.name = 'ROOM_Floor_01';
  floor.receiveShadow = true;

  const backWall = new THREE.Mesh(
    new THREE.BoxGeometry(1, 1, 0.16),
    createRoomMaterial('MAT_Room_Wall', roomState.wallColor),
  );
  backWall.name = 'ROOM_Wall_Back_01';
  backWall.castShadow = true;
  backWall.receiveShadow = true;

  const leftWall = new THREE.Mesh(
    new THREE.BoxGeometry(0.16, 1, 1),
    backWall.material,
  );
  leftWall.name = 'ROOM_Wall_Left_01';
  leftWall.castShadow = true;
  leftWall.receiveShadow = true;

  const trimMaterial = createRoomMaterial('MAT_Room_Trim', '#9b6646');
  const backTopTrim = new THREE.Mesh(new THREE.BoxGeometry(1, 0.12, 0.22), trimMaterial);
  backTopTrim.name = 'ROOM_Trim_Back_Top_01';
  const leftTopTrim = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.12, 1), trimMaterial);
  leftTopTrim.name = 'ROOM_Trim_Left_Top_01';
  const cornerPost = new THREE.Mesh(new THREE.BoxGeometry(0.24, 1, 0.24), trimMaterial);
  cornerPost.name = 'ROOM_Corner_Post_01';

  [floor, backWall, leftWall, backTopTrim, leftTopTrim, cornerPost].forEach((mesh) => {
    mesh.userData.editorRoom = true;
    roomGroup.add(mesh);
  });

  return { floor, backWall, leftWall, backTopTrim, leftTopTrim, cornerPost };
}

function updateRoomBlock() {
  const width = Math.max(1, roomState.width);
  const depth = Math.max(1, roomState.depth);
  const height = Math.max(0.5, roomState.height);
  const thickness = 0.16;

  roomMeshes.floor.scale.set(width, 1, depth);
  roomMeshes.floor.position.set(0, -0.06, 0);

  roomMeshes.backWall.scale.set(width, height, 1);
  roomMeshes.backWall.position.set(0, height / 2, -depth / 2);

  roomMeshes.leftWall.scale.set(1, height, depth);
  roomMeshes.leftWall.position.set(-width / 2, height / 2, 0);

  roomMeshes.backTopTrim.scale.set(width + thickness, 1, 1);
  roomMeshes.backTopTrim.position.set(0, height + 0.06, -depth / 2 - thickness * 0.2);

  roomMeshes.leftTopTrim.scale.set(1, 1, depth + thickness);
  roomMeshes.leftTopTrim.position.set(-width / 2 - thickness * 0.2, height + 0.06, 0);

  roomMeshes.cornerPost.scale.set(1, height + 0.2, 1);
  roomMeshes.cornerPost.position.set(-width / 2 - thickness * 0.15, height / 2, -depth / 2 - thickness * 0.15);

  roomMeshes.floor.material.color.set(roomState.floorColor);
  roomMeshes.backWall.material.color.set(roomState.wallColor);
  roomMeshes.leftWall.material = roomMeshes.backWall.material;

  applyRoomTexture(roomMeshes.floor.material, roomState.floorTexture, width / 2, depth / 2);
  applyRoomTexture(roomMeshes.backWall.material, roomState.wallTexture, width / 2, height / 1.5);
  fields.roomWidth.value = String(width);
  fields.roomDepth.value = String(depth);
  fields.roomHeight.value = String(height);
}

function applyRoomTexture(material, texture, repeatX, repeatY) {
  if (!texture) {
    material.map = null;
    material.needsUpdate = true;
    return;
  }
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(Math.max(1, repeatX), Math.max(1, repeatY));
  texture.colorSpace = THREE.SRGBColorSpace;
  material.map = texture;
  material.needsUpdate = true;
}

function loadRoomTexture(file, target) {
  if (!file) return;
  const url = URL.createObjectURL(file);
  textureLoader.load(url, (texture) => {
    roomState[target] = texture;
    updateRoomBlock();
    setStatus(`Applied ${file.name} to ${target === 'floorTexture' ? 'floor' : 'walls'}`);
    URL.revokeObjectURL(url);
  });
}

function prepareImportedScene(gltf, fileName, options = {}) {
  const base = uniqueId(normalizeName(fileName), roots);
  const root = new THREE.Group();
  root.name = base;
  root.userData.meta = makeDefaultMeta(base);
  root.userData.meta.assetName = fileName;

  const asset = gltf.scene;
  asset.name = `${base}__asset`;
  asset.traverse((child) => {
    if (child.isMesh) {
      child.castShadow = true;
      child.receiveShadow = true;
      child.userData.ownerRoot = base;
      if (child.material) {
        const materials = Array.isArray(child.material) ? child.material : [child.material];
        materials.forEach((mat) => {
          mat = mat.clone();
        });
      }
    }
  });
  root.add(asset);
  if (options.scale) {
    root.scale.setScalar(options.scale);
  } else {
    normalizeImportedScale(root);
  }
  scene.add(root);
  roots.push(root);
  createOrUpdateLabel(root, root.userData.meta.id);
  return root;
}

function normalizeImportedScale(root) {
  const box = new THREE.Box3().setFromObject(root);
  if (box.isEmpty()) return;
  const size = box.getSize(new THREE.Vector3());
  const maxSide = Math.max(size.x, size.y, size.z);
  if (!Number.isFinite(maxSide) || maxSide <= 0) return;
  if (maxSide > 10) {
    root.scale.multiplyScalar(2 / maxSide);
  } else if (maxSide < 0.05) {
    root.scale.multiplyScalar(0.5 / maxSide);
  }
}

function loadAssetFromUrl(asset) {
  setStatus(`Loading ${asset.name}`);
  loader.load(
    asset.url,
    (gltf) => {
      const root = prepareImportedScene(gltf, asset.name, { scale: asset.scale });
      root.userData.meta.assetPath = asset.path;
      root.userData.meta.assetUrl = asset.url;
      root.userData.meta.defaultScale = asset.scale;
      select(root);
      frameSelected();
      renderLists();
      setStatus(`Added ${asset.name}`);
    },
    undefined,
    (error) => setStatus(`Could not load ${asset.name}: ${error.message}`),
  );
}

function createMarker(root, markerType, worldPosition = null) {
  const geometry = new THREE.SphereGeometry(0.08, 16, 8);
  const colors = { approach: 0x49c78b, sit: 0xe29f45, lookAt: 0x62a8ff };
  const material = new THREE.MeshStandardMaterial({
    color: colors[markerType] ?? 0xffffff,
    emissive: colors[markerType] ?? 0xffffff,
    emissiveIntensity: 0.18,
  });
  const marker = new THREE.Mesh(geometry, material);
  marker.name = `${root.userData.meta.id}__${markerType}`;
  marker.userData.markerFor = root.uuid;
  marker.userData.markerType = markerType;
  marker.position.copy(worldPosition ?? root.position.clone().add(new THREE.Vector3(0, 0, -0.9)));
  scene.add(marker);
  createOrUpdateLabel(marker, markerType);
  root.userData.markers ??= {};
  root.userData.markers[markerType] = marker;
  root.userData.meta.interactionPoints[markerType] = marker.position.toArray().map(round3);
  renderLists();
  return marker;
}

function select(object) {
  selected = object && roots.includes(object) ? object : null;
  selectedMarker = object?.userData.markerFor ? object : null;
  updateActiveControls();
  syncInspectorFromSelection();
  renderLists();
}

function updateActiveControls() {
  transform.detach();
  objectControls.setObjectToMove(objectControlsDummy);
  orbit.enabled = activeControlMode !== 'objectControls';

  if (activeControlMode === 'objectControls') {
    if (selected) {
      objectControls.setObjectToMove(selected);
    }
    return;
  }

  if (selected || selectedMarker) {
    transform.attach(selected ?? selectedMarker);
    transform.setMode(activeControlMode);
    transform.visible = true;
  }
}

function currentTarget() {
  return selected ?? selectedMarker;
}

function updatePointerFromEvent(event) {
  const rect = canvas.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
}

function hitSelectableRoot() {
  const targets = [];
  roots.forEach((root) => targets.push(root));
  roots.forEach((root) => Object.values(root.userData.markers ?? {}).forEach((marker) => targets.push(marker)));
  const hits = raycaster.intersectObjects(targets, true);
  return hits.length ? selectableRoot(hits[0].object) : null;
}

function startObjectDrag(event) {
  if (activeControlMode !== 'translate') return false;
  updatePointerFromEvent(event);
  const hit = hitSelectableRoot();
  const root = hit && roots.includes(hit) ? hit : null;
  if (!root) return false;

  select(root);
  dragPlane.constant = -root.position.y;
  const hitPoint = new THREE.Vector3();
  if (!raycaster.ray.intersectPlane(dragPlane, hitPoint)) return false;

  objectDrag = {
    root,
    offset: root.position.clone().sub(hitPoint),
    moved: false,
    pointerId: event.pointerId,
  };
  canvas.setPointerCapture?.(event.pointerId);
  orbit.enabled = false;
  transform.detach();
  setStatus(`Dragging ${root.userData.meta?.id ?? root.name}`);
  return true;
}

function updateObjectDrag(event) {
  if (!objectDrag) return;
  updatePointerFromEvent(event);
  const hitPoint = new THREE.Vector3();
  if (!raycaster.ray.intersectPlane(dragPlane, hitPoint)) return;
  objectDrag.root.position.copy(hitPoint.add(objectDrag.offset));
  objectDrag.moved = true;
  syncInspectorFromSelection();
  renderLists();
}

function finishObjectDrag() {
  if (!objectDrag) return false;
  const didMove = objectDrag.moved;
  const root = objectDrag.root;
  canvas.releasePointerCapture?.(objectDrag.pointerId);
  objectDrag = null;
  orbit.enabled = activeControlMode !== 'objectControls';
  updateActiveControls();
  setStatus(didMove ? `Moved ${root.userData.meta?.id ?? root.name}` : 'Move mode');
  return didMove;
}

function syncInspectorFromSelection() {
  const target = currentTarget();
  if (!target) {
    inspectorEl.classList.add('hidden');
    emptyStateEl.classList.remove('hidden');
    return;
  }

  inspectorEl.classList.remove('hidden');
  emptyStateEl.classList.add('hidden');

  const metaRoot = selected ?? roots.find((root) => root.uuid === selectedMarker?.userData.markerFor);
  const meta = metaRoot?.userData.meta ?? makeDefaultMeta(target.name);
  fields.name.value = selectedMarker ? target.name : meta.id;
  fields.type.value = meta.type ?? '';
  fields.zone.value = meta.zone ?? '';
  fields.humanName.value = meta.humanName ?? '';
  fields.actions.value = (meta.actions ?? []).join(',');
  fields.posX.value = target.position.x.toFixed(3);
  fields.posY.value = target.position.y.toFixed(3);
  fields.posZ.value = target.position.z.toFixed(3);
  fields.rotX.value = THREE.MathUtils.radToDeg(target.rotation.x).toFixed(1);
  fields.rotY.value = THREE.MathUtils.radToDeg(target.rotation.y).toFixed(1);
  fields.rotZ.value = THREE.MathUtils.radToDeg(target.rotation.z).toFixed(1);
  fields.scaleX.value = target.scale.x.toFixed(3);
  fields.scaleY.value = target.scale.y.toFixed(3);
  fields.scaleZ.value = target.scale.z.toFixed(3);
  fields.color.value = getSelectedColor(target);
}

function getSelectedColor(target) {
  let color = '#ffffff';
  target.traverse?.((child) => {
    if (child.isMesh && child.material?.color) {
      color = `#${child.material.color.getHexString()}`;
    }
  });
  return color;
}

function applyInspectorToSelection() {
  const target = currentTarget();
  if (!target) return;

  if (selected) {
    const meta = selected.userData.meta;
    meta.id = fields.name.value.trim() || selected.name;
    selected.name = meta.id;
    createOrUpdateLabel(selected, meta.id);
    meta.type = fields.type.value.trim();
    meta.zone = fields.zone.value.trim();
    meta.humanName = fields.humanName.value.trim();
    meta.actions = fields.actions.value.split(',').map((item) => item.trim()).filter(Boolean);
  } else if (selectedMarker) {
    selectedMarker.name = fields.name.value.trim() || selectedMarker.name;
    createOrUpdateLabel(selectedMarker, selectedMarker.userData.markerType);
  }

  target.position.set(num(fields.posX), num(fields.posY), num(fields.posZ));
  target.rotation.set(
    THREE.MathUtils.degToRad(num(fields.rotX)),
    THREE.MathUtils.degToRad(num(fields.rotY)),
    THREE.MathUtils.degToRad(num(fields.rotZ)),
  );
  target.scale.set(num(fields.scaleX, 1), num(fields.scaleY, 1), num(fields.scaleZ, 1));
  updateMarkerMeta();
  renderLists();
}

function updateMarkerMeta() {
  roots.forEach((root) => {
    const points = {};
    Object.entries(root.userData.markers ?? {}).forEach(([key, marker]) => {
      points[key] = marker.position.toArray().map(round3);
    });
    root.userData.meta.interactionPoints = points;
  });
}

function applyColor(hex) {
  const target = currentTarget();
  if (!target) return;
  target.traverse((child) => {
    if (!child.isMesh || !child.material) return;
    const materials = Array.isArray(child.material) ? child.material : [child.material];
    materials.forEach((mat) => {
      if (mat.color) {
        mat.color.set(hex);
        mat.needsUpdate = true;
      }
    });
  });
}

function applyTexture(file) {
  const target = currentTarget();
  if (!target || !file) return;
  const url = URL.createObjectURL(file);
  textureLoader.load(url, (texture) => {
    texture.colorSpace = THREE.SRGBColorSpace;
    target.traverse((child) => {
      if (!child.isMesh || !child.material) return;
      const materials = Array.isArray(child.material) ? child.material : [child.material];
      materials.forEach((mat) => {
        mat.map = texture;
        mat.needsUpdate = true;
      });
    });
    setStatus(`Applied ${file.name}`);
  });
}

function renderLists() {
  renderAssetLibrary();
  objectListEl.innerHTML = '';
  roots.forEach((root) => {
    const meta = root.userData.meta;
    const item = document.createElement('button');
    item.className = `object-item ${selected === root ? 'selected' : ''}`;
    item.innerHTML = `<strong>${escapeHtml(meta.id)}</strong><small>${escapeHtml(meta.type)} · ${escapeHtml(meta.zone)}</small>`;
    item.addEventListener('click', () => select(root));
    objectListEl.append(item);
  });

  markerListEl.innerHTML = '';
  roots.forEach((root) => {
    Object.entries(root.userData.markers ?? {}).forEach(([type, marker]) => {
      const item = document.createElement('button');
      item.className = `marker-item ${selectedMarker === marker ? 'selected' : ''}`;
      item.innerHTML = `<strong>${escapeHtml(type)}</strong><small>${escapeHtml(root.userData.meta.id)}</small>`;
      item.addEventListener('click', () => select(marker));
      markerListEl.append(item);
    });
  });
}

function renderAssetLibrary() {
  const query = assetSearchEl.value.trim().toLowerCase();
  assetLibraryEl.innerHTML = '';
  projectAssets
    .filter((asset) => !query || `${asset.name} ${asset.path}`.toLowerCase().includes(query))
    .forEach((asset) => {
      const item = document.createElement('button');
      item.className = 'asset-item';
      item.innerHTML = `<strong>${escapeHtml(asset.name)}</strong><small>${escapeHtml(asset.path)}</small>`;
      item.addEventListener('click', () => loadAssetFromUrl(asset));
      assetLibraryEl.append(item);
    });
}

function createOrUpdateLabel(target, text) {
  let sprite = labelSprites.get(target.uuid);
  if (!sprite) {
    const material = new THREE.SpriteMaterial({
      map: makeLabelTexture(text),
      transparent: true,
      depthTest: false,
    });
    sprite = new THREE.Sprite(material);
    sprite.name = `${target.name}__label`;
    sprite.userData.labelFor = target.uuid;
    sprite.renderOrder = 10;
    scene.add(sprite);
    labelSprites.set(target.uuid, sprite);
  } else {
    sprite.material.map?.dispose();
    sprite.material.map = makeLabelTexture(text);
    sprite.material.needsUpdate = true;
    sprite.name = `${target.name}__label`;
  }
  updateLabelPosition(target, sprite);
}

function updateLabelPosition(target, sprite = labelSprites.get(target.uuid)) {
  if (!sprite) return;
  const box = new THREE.Box3().setFromObject(target);
  const center = box.isEmpty() ? target.position.clone() : box.getCenter(new THREE.Vector3());
  const height = box.isEmpty() ? 0.35 : Math.max(0.35, box.max.y - box.min.y);
  sprite.position.copy(center).add(new THREE.Vector3(0, height * 0.62 + 0.2, 0));
  sprite.scale.set(1.1, 0.28, 1);
}

function makeLabelTexture(text) {
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 128;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = 'rgba(18, 20, 19, 0.82)';
  roundRect(ctx, 8, 20, 496, 88, 14);
  ctx.fill();
  ctx.strokeStyle = 'rgba(226, 159, 69, 0.9)';
  ctx.lineWidth = 3;
  ctx.stroke();
  ctx.fillStyle = '#f4eddf';
  ctx.font = '600 34px Inter, system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(String(text).slice(0, 32), 256, 64, 460);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function roundRect(ctx, x, y, width, height, radius) {
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.arcTo(x + width, y, x + width, y + height, radius);
  ctx.arcTo(x + width, y + height, x, y + height, radius);
  ctx.arcTo(x, y + height, x, y, radius);
  ctx.arcTo(x, y, x + width, y, radius);
  ctx.closePath();
}

function exportConfig() {
  updateMarkerMeta();
  const config = createConfigPayload({
    sceneId: fields.sceneId.value,
    displayName: fields.displayName.value,
  }, roots);
  config.room = {
    id: roomGroup.name,
    width: roomState.width,
    depth: roomState.depth,
    height: roomState.height,
    floorColor: roomState.floorColor,
    wallColor: roomState.wallColor,
    hasFloorTexture: Boolean(roomState.floorTexture),
    hasWallTexture: Boolean(roomState.wallTexture),
  };
  downloadBlob(JSON.stringify(config, null, 2), 'environment-config.json', 'application/json');
}

function saveLocations() {
  const payload = createLocationsPayload(roots);
  localStorage.setItem(LOCATION_STORAGE_KEY, JSON.stringify(payload));
  setStatus(`Saved ${payload.objects.length} object location(s)`);
}

function loadLocations() {
  const raw = localStorage.getItem(LOCATION_STORAGE_KEY);
  if (!raw) {
    setStatus('No saved locations found');
    return;
  }

  let payload;
  try {
    payload = JSON.parse(raw);
  } catch {
    setStatus('Saved locations are not valid JSON');
    return;
  }

  const applied = applySavedLocations(roots, payload);
  updateMarkerMeta();
  syncInspectorFromSelection();
  renderLists();
  setStatus(`Loaded ${applied} saved location(s)`);
}

function exportGlb() {
  const exportScene = scene.clone(true);
  const editorNames = new Set(['EditorGrid', 'EditorFloorPickPlane', 'EditorTransformControlsHelper']);
  exportScene.children
    .filter((child) => editorNames.has(child.name) || child.type === 'TransformControlsPlane' || child.userData.labelFor)
    .forEach((child) => exportScene.remove(child));
  exporter.parse(
    exportScene,
    (result) => {
      if (result instanceof ArrayBuffer) {
        downloadBlob(result, 'environment.glb', 'model/gltf-binary');
      } else {
        downloadBlob(JSON.stringify(result, null, 2), 'environment.gltf', 'model/gltf+json');
      }
    },
    (error) => setStatus(`GLB export failed: ${error.message}`),
    { binary: true },
  );
}

function exportSelectedTextures() {
  const target = currentTarget();
  if (!target) return;
  let count = 0;
  target.traverse((child) => {
    if (!child.isMesh || !child.material) return;
    const materials = Array.isArray(child.material) ? child.material : [child.material];
    materials.forEach((mat, matIndex) => {
      if (!mat.map?.image) return;
      const image = mat.map.image;
      const out = document.createElement('canvas');
      out.width = image.width || image.videoWidth || 1024;
      out.height = image.height || image.videoHeight || 1024;
      const ctx = out.getContext('2d');
      ctx.drawImage(image, 0, 0, out.width, out.height);
      out.toBlob((blob) => {
        if (blob) downloadBlob(blob, `${target.name}_${child.name}_${matIndex}_texture.png`, 'image/png');
      });
      count += 1;
    });
  });
  setStatus(count ? `Exported ${count} texture image(s)` : 'No texture map found on selection');
}

function frameSelected() {
  const target = currentTarget();
  if (!target) return;
  const box = new THREE.Box3().setFromObject(target);
  if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3());
  const radius = box.getSize(new THREE.Vector3()).length() || 2;
  orbit.target.copy(center);
  camera.position.copy(center).add(new THREE.Vector3(radius * 0.8, radius * 0.55, radius * 0.95));
  camera.lookAt(center);
}

function deleteSelected() {
  if (selectedMarker) {
    const root = roots.find((item) => item.uuid === selectedMarker.userData.markerFor);
    if (root?.userData.markers) delete root.userData.markers[selectedMarker.userData.markerType];
    selectedMarker.removeFromParent();
    const label = labelSprites.get(selectedMarker.uuid);
    label?.removeFromParent();
    labelSprites.delete(selectedMarker.uuid);
    selectedMarker.geometry?.dispose();
    selectedMarker.material?.dispose();
    select(null);
    updateMarkerMeta();
    return;
  }
  if (!selected) return;
  Object.values(selected.userData.markers ?? {}).forEach((marker) => marker.removeFromParent());
  Object.values(selected.userData.markers ?? {}).forEach((marker) => {
    labelSprites.get(marker.uuid)?.removeFromParent();
    labelSprites.delete(marker.uuid);
  });
  labelSprites.get(selected.uuid)?.removeFromParent();
  labelSprites.delete(selected.uuid);
  selected.removeFromParent();
  roots.splice(roots.indexOf(selected), 1);
  select(null);
}

function importProject(file) {
  const reader = new FileReader();
  reader.onload = () => {
    const data = JSON.parse(reader.result);
    fields.sceneId.value = data.sceneId ?? fields.sceneId.value;
    fields.displayName.value = data.displayName ?? fields.displayName.value;
    setStatus('Project config loaded. Reimport GLB files, then use the positions as reference.');
  };
  reader.readAsText(file);
}

function downloadBlob(data, filename, type) {
  const blob = data instanceof Blob ? data : new Blob([data], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

document.querySelector('#assetInput').addEventListener('change', async (event) => {
  const files = [...event.target.files];
  for (const file of files) {
    const url = URL.createObjectURL(file);
    await new Promise((resolve, reject) => {
      loader.load(
        url,
        (gltf) => {
          const root = prepareImportedScene(gltf, file.name);
          select(root);
          frameSelected();
          setStatus(`Imported ${file.name}`);
          URL.revokeObjectURL(url);
          resolve();
        },
        undefined,
        reject,
      );
    });
  }
  renderLists();
});

assetSearchEl.addEventListener('input', renderAssetLibrary);

document.querySelector('#projectInput').addEventListener('change', (event) => {
  const [file] = event.target.files;
  if (file) importProject(file);
});

document.querySelector('#textureInput').addEventListener('change', (event) => {
  applyTexture(event.target.files[0]);
});

document.querySelector('#floorTextureInput').addEventListener('change', (event) => {
  loadRoomTexture(event.target.files[0], 'floorTexture');
});

document.querySelector('#wallTextureInput').addEventListener('change', (event) => {
  loadRoomTexture(event.target.files[0], 'wallTexture');
});

document.querySelector('#resetRoomTextures').addEventListener('click', () => {
  roomState.floorTexture = null;
  roomState.wallTexture = null;
  updateRoomBlock();
  setStatus('Room textures reset');
});

document.querySelector('#exportConfig').addEventListener('click', exportConfig);
document.querySelector('#exportGlb').addEventListener('click', exportGlb);
document.querySelector('#saveLocations').addEventListener('click', saveLocations);
document.querySelector('#loadLocations').addEventListener('click', loadLocations);
document.querySelector('#exportTextures').addEventListener('click', exportSelectedTextures);
document.querySelector('#frameSelected').addEventListener('click', frameSelected);
document.querySelector('#deleteSelected').addEventListener('click', deleteSelected);

document.querySelectorAll('[data-mode]').forEach((button) => {
  button.addEventListener('click', () => {
    document.querySelectorAll('[data-mode]').forEach((item) => item.classList.remove('active'));
    button.classList.add('active');
    activeControlMode = button.dataset.mode;
    updateActiveControls();
    setStatus(activeControlMode === 'objectControls'
      ? 'ObjectControls active: drag selected object to rotate it'
      : `${activeControlMode} mode`);
  });
});

document.querySelectorAll('[data-marker]').forEach((button) => {
  button.addEventListener('click', () => {
    if (!selected) return;
    const marker = createMarker(selected, button.dataset.marker);
    select(marker);
  });
});

[
  fields.name,
  fields.type,
  fields.zone,
  fields.humanName,
  fields.actions,
  fields.posX,
  fields.posY,
  fields.posZ,
  fields.rotX,
  fields.rotY,
  fields.rotZ,
  fields.scaleX,
  fields.scaleY,
  fields.scaleZ,
].forEach((field) => field.addEventListener('input', applyInspectorToSelection));

fields.color.addEventListener('input', (event) => applyColor(event.target.value));

[fields.roomWidth, fields.roomDepth, fields.roomHeight].forEach((field) => {
  field.addEventListener('input', () => {
    roomState.width = num(fields.roomWidth, roomState.width);
    roomState.depth = num(fields.roomDepth, roomState.depth);
    roomState.height = num(fields.roomHeight, roomState.height);
    updateRoomBlock();
  });
});

fields.floorColor.addEventListener('input', (event) => {
  roomState.floorColor = event.target.value;
  updateRoomBlock();
});

fields.wallColor.addEventListener('input', (event) => {
  roomState.wallColor = event.target.value;
  updateRoomBlock();
});

canvas.addEventListener('pointerdown', (event) => {
  if (transform.dragging || transformInteracting) return;
  if (event.target.closest?.('.viewport-tools')) return;
  pickStart = { x: event.clientX, y: event.clientY };
});

canvas.addEventListener('pointerup', (event) => {
  if (!pickStart || transform.dragging || transformInteracting) {
    pickStart = null;
    return;
  }
  const moved = Math.hypot(event.clientX - pickStart.x, event.clientY - pickStart.y);
  pickStart = null;
  if (moved > 4) return;
  updatePointerFromEvent(event);
  select(hitSelectableRoot());
});

canvas.addEventListener('pointercancel', () => {
  finishObjectDrag();
  pickStart = null;
});

window.addEventListener('resize', resize);

function resize() {
  const rect = canvas.parentElement.getBoundingClientRect();
  camera.aspect = rect.width / rect.height;
  camera.updateProjectionMatrix();
  renderer.setSize(rect.width, rect.height, false);
}

function animate() {
  orbit.update();
  if (objectControls.isUserInteractionActive()) {
    syncInspectorFromSelection();
    renderLists();
  }
  roots.forEach((root) => {
    updateLabelPosition(root);
    Object.values(root.userData.markers ?? {}).forEach((marker) => updateLabelPosition(marker));
  });
  renderer.render(scene, camera);
  requestAnimationFrame(animate);
}

resize();
renderLists();
animate();

fetch('/project-assets.json')
  .then((response) => response.json())
  .then((assets) => {
    projectAssets = assets;
    renderAssetLibrary();
    setStatus(`Ready · ${assets.length} project assets`);
  })
  .catch(() => {
    projectAssets = [];
    setStatus('Ready · project asset manifest not found');
  });
