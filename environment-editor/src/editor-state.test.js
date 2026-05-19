import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {
  applySavedLocations,
  createConfigPayload,
  createLocationsPayload,
  escapeHtml,
  makeDefaultMeta,
  normalizeName,
  num,
  objectLocationPayload,
  round3,
  uniqueId,
} from './editor-state.js';

function makeRoot(id, overrides = {}) {
  const root = new THREE.Group();
  root.name = id;
  root.userData.meta = {
    ...makeDefaultMeta(id),
    ...overrides,
  };
  return root;
}

test('normalizeName creates stable object ids from asset filenames', () => {
  assert.equal(normalizeName('sofa-10.glb'), 'sofa_10');
  assert.equal(normalizeName(' corner kitchen unit!.GLB '), 'corner_kitchen_unit');
  assert.equal(normalizeName('...'), 'asset');
});

test('uniqueId appends a numeric suffix when an id already exists', () => {
  const roots = [
    makeRoot('sofa_10'),
    makeRoot('sofa_10_2'),
  ];

  assert.equal(uniqueId('sofa_10', roots), 'sofa_10_3');
  assert.equal(uniqueId('chair_2', roots), 'chair_2');
});

test('objectLocationPayload serializes transforms rounded to 3 decimals', () => {
  const root = makeRoot('sofa_10', {
    assetName: 'sofa-10.glb',
    assetPath: 'frontend/models/blueprint3d/sofa-10.glb',
  });
  root.position.set(1.23456, 0, -2.98765);
  root.rotation.set(0, Math.PI / 2, Math.PI);
  root.scale.set(1.11119, 2, 0.33339);

  assert.deepEqual(objectLocationPayload(root), {
    id: 'sofa_10',
    assetName: 'sofa-10.glb',
    assetPath: 'frontend/models/blueprint3d/sofa-10.glb',
    position: [1.235, 0, -2.988],
    rotation: [0, 1.571, 3.142],
    scale: [1.111, 2, 0.333],
  });
});

test('createLocationsPayload includes all roots and caller supplied timestamp', () => {
  const roots = [makeRoot('sofa_10'), makeRoot('chair_2')];
  roots[1].position.set(4, 0, 2);

  assert.deepEqual(createLocationsPayload(roots, '2026-05-10T00:00:00.000Z'), {
    savedAt: '2026-05-10T00:00:00.000Z',
    objects: [
      {
        id: 'sofa_10',
        assetName: 'sofa_10',
        assetPath: '',
        position: [0, 0, 0],
        rotation: [0, 0, 0],
        scale: [1, 1, 1],
      },
      {
        id: 'chair_2',
        assetName: 'chair_2',
        assetPath: '',
        position: [4, 0, 2],
        rotation: [0, 0, 0],
        scale: [1, 1, 1],
      },
    ],
  });
});

test('applySavedLocations matches by id, asset path, or asset name', () => {
  const byId = makeRoot('sofa_10', { assetName: 'old.glb' });
  const byPath = makeRoot('renamed_storage', {
    assetName: 'storage-copy.glb',
    assetPath: 'frontend/models/blueprint3d/storage-1.glb',
  });
  const byName = makeRoot('renamed_chair', { assetName: 'chair-2.glb' });

  const applied = applySavedLocations([byId, byPath, byName], {
    objects: [
      { id: 'sofa_10', position: [1, 0, 2], rotation: [0, 0.5, 0], scale: [1, 1, 1] },
      { id: 'storage_old', assetPath: 'frontend/models/blueprint3d/storage-1.glb', position: [3, 0, 4], rotation: [0, 1, 0], scale: [2, 2, 2] },
      { id: 'chair_old', assetName: 'chair-2.glb', position: [5, 0, 6], rotation: [0, 1.5, 0], scale: [0.5, 0.5, 0.5] },
      { id: 'missing', position: [7, 0, 8] },
    ],
  });

  assert.equal(applied, 3);
  assert.deepEqual(byId.position.toArray(), [1, 0, 2]);
  assert.deepEqual(byPath.position.toArray(), [3, 0, 4]);
  assert.deepEqual(byName.position.toArray(), [5, 0, 6]);
  assert.deepEqual(byPath.scale.toArray(), [2, 2, 2]);
});

test('createConfigPayload exports scene metadata and object interaction data', () => {
  const root = makeRoot('sofa_10', {
    humanName: 'Sofa',
    type: 'sofa',
    zone: 'LivingRoom',
    assetName: 'sofa-10.glb',
    assetPath: 'frontend/models/blueprint3d/sofa-10.glb',
    assetUrl: '/@fs/sofa-10.glb',
    defaultScale: 0.5,
    actions: ['inspect', 'moveTo', 'sit'],
    interactionPoints: { sit: [1, 0.6, 2] },
  });
  root.position.set(1.2, 0, 2.3);

  assert.deepEqual(createConfigPayload({ sceneId: ' nami ', displayName: ' Nami Studio ' }, [root]), {
    sceneId: 'nami',
    displayName: 'Nami Studio',
    units: 'meters',
    objects: [
      {
        id: 'sofa_10',
        humanName: 'Sofa',
        type: 'sofa',
        zone: 'LivingRoom',
        assetName: 'sofa-10.glb',
        assetPath: 'frontend/models/blueprint3d/sofa-10.glb',
        assetUrl: '/@fs/sofa-10.glb',
        defaultScale: 0.5,
        position: [1.2, 0, 2.3],
        rotation: [0, 0, 0],
        scale: [1, 1, 1],
        actions: ['inspect', 'moveTo', 'sit'],
        interactionPoints: { sit: [1, 0.6, 2] },
      },
    ],
  });
});

test('small utility helpers handle invalid numeric input and html escaping', () => {
  assert.equal(round3(1.23456), 1.235);
  assert.equal(num({ value: '3.14' }), 3.14);
  assert.equal(num({ value: 'nope' }, 9), 9);
  assert.equal(escapeHtml('<button name="x">& \'</button>'), '&lt;button name=&quot;x&quot;&gt;&amp; &#039;&lt;/button&gt;');
});
