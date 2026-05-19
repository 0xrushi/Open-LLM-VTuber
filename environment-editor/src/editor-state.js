export const LOCATION_STORAGE_KEY = 'environment-editor-object-locations-v1';

export function makeDefaultMeta(name) {
  return {
    id: name,
    humanName: name.replaceAll('_', ' '),
    type: 'prop',
    zone: 'Room',
    actions: ['inspect', 'moveTo'],
    interactionPoints: {},
    assetName: name,
  };
}

export function normalizeName(name) {
  return name
    .replace(/\.[^.]+$/, '')
    .replace(/[^a-zA-Z0-9_]+/g, '_')
    .replace(/^_+|_+$/g, '') || 'asset';
}

export function uniqueId(base, roots) {
  let id = base;
  let index = 1;
  while (roots.some((root) => root.userData.meta?.id === id)) {
    index += 1;
    id = `${base}_${index}`;
  }
  return id;
}

export function round3(value) {
  return Number(value.toFixed(3));
}

export function num(field, fallback = 0) {
  const value = Number.parseFloat(field.value);
  return Number.isFinite(value) ? value : fallback;
}

export function escapeHtml(value = '') {
  return String(value).replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;',
  })[char]);
}

export function objectLocationPayload(root) {
  const meta = root.userData.meta ?? {};
  return {
    id: meta.id ?? root.name,
    assetName: meta.assetName ?? '',
    assetPath: meta.assetPath ?? '',
    position: root.position.toArray().map(round3),
    rotation: [root.rotation.x, root.rotation.y, root.rotation.z].map(round3),
    scale: root.scale.toArray().map(round3),
  };
}

export function createLocationsPayload(roots, savedAt = new Date().toISOString()) {
  return {
    savedAt,
    objects: roots.map(objectLocationPayload),
  };
}

export function findRootForSavedLocation(roots, saved) {
  return roots.find((item) => {
    const meta = item.userData.meta ?? {};
    return (
      meta.id === saved.id ||
      (saved.assetPath && meta.assetPath === saved.assetPath) ||
      (saved.assetName && meta.assetName === saved.assetName)
    );
  });
}

export function applySavedLocations(roots, payload) {
  let applied = 0;
  for (const saved of payload.objects ?? []) {
    const root = findRootForSavedLocation(roots, saved);
    if (!root) continue;
    root.position.fromArray(saved.position ?? root.position.toArray());
    root.rotation.set(...(saved.rotation ?? [root.rotation.x, root.rotation.y, root.rotation.z]));
    root.scale.fromArray(saved.scale ?? root.scale.toArray());
    applied += 1;
  }
  return applied;
}

export function createConfigPayload({ sceneId, displayName }, roots) {
  const objects = roots.map((root) => ({
    id: root.userData.meta.id,
    humanName: root.userData.meta.humanName,
    type: root.userData.meta.type,
    zone: root.userData.meta.zone,
    assetName: root.userData.meta.assetName,
    assetPath: root.userData.meta.assetPath,
    assetUrl: root.userData.meta.assetUrl,
    defaultScale: root.userData.meta.defaultScale,
    position: root.position.toArray().map(round3),
    rotation: [root.rotation.x, root.rotation.y, root.rotation.z].map(round3),
    scale: root.scale.toArray().map(round3),
    actions: root.userData.meta.actions,
    interactionPoints: root.userData.meta.interactionPoints,
  }));

  return {
    sceneId: sceneId.trim() || 'custom_environment',
    displayName: displayName.trim() || 'Custom Environment',
    units: 'meters',
    objects,
  };
}
