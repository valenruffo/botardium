import test from 'node:test';
import assert from 'node:assert/strict';

import { resolveUpdateCheckState } from './update-check.js';

test('desktop native check returns available state', () => {
  const resolution = resolveUpdateCheckState({
    runtime: 'desktop',
    appVersion: '1.1.0',
    nativeUpdate: { version: '1.2.0', body: '  Release notes  ' },
  });

  assert.equal(resolution.phase, 'available');
  assert.equal(resolution.message, 'Update nativo disponible: 1.2.0.');
  assert.deepEqual(resolution.nativeUpdateMeta, { version: '1.2.0', notes: 'Release notes' });
  assert.equal(resolution.keepNativeUpdate, true);
});

test('desktop native check returns no_update when feed has no update', () => {
  const resolution = resolveUpdateCheckState({
    runtime: 'desktop',
    appVersion: '1.1.0',
  });

  assert.equal(resolution.phase, 'no_update');
  assert.equal(resolution.message, 'Ya estás en la última versión (1.1.0).');
  assert.equal(resolution.keepNativeUpdate, false);
});

test('browser runtime uses fallback available state', () => {
  const resolution = resolveUpdateCheckState({
    runtime: 'browser',
    appVersion: '1.1.0',
    fallbackStatus: {
      ok: true,
      current_version: '1.1.0',
      latest_version: '1.2.0',
      update_available: true,
    },
  });

  assert.equal(resolution.phase, 'fallback');
  assert.equal(resolution.message, 'Release disponible: 1.2.0. En navegador solo mostramos información.');
  assert.equal(resolution.toast, null);
});

test('browser runtime uses fallback no_update state', () => {
  const resolution = resolveUpdateCheckState({
    runtime: 'browser',
    appVersion: '1.1.0',
    fallbackStatus: {
      ok: true,
      current_version: '1.1.0',
      update_available: false,
    },
  });

  assert.equal(resolution.phase, 'no_update');
  assert.equal(resolution.message, 'Info de releases al día. Esta sesión web corre la versión 1.1.0.');
});

test('desktop native failure falls back to manual update when fallback reports update', () => {
  const resolution = resolveUpdateCheckState({
    runtime: 'desktop',
    appVersion: '1.1.0',
    nativeErrorDetail: 'network timeout',
    fallbackStatus: {
      ok: true,
      current_version: '1.1.0',
      latest_version: '1.2.0',
      update_available: true,
    },
  });

  assert.equal(resolution.phase, 'fallback');
  assert.deepEqual(resolution.toast, {
    level: 'warning',
    message: 'Updater nativo no disponible. Podés descargar el instalador manualmente.',
  });
});

test('desktop native failure falls back to no_update when fallback reports false', () => {
  const resolution = resolveUpdateCheckState({
    runtime: 'desktop',
    appVersion: '1.1.0',
    nativeErrorDetail: 'network timeout',
    fallbackStatus: {
      ok: true,
      current_version: '1.1.0',
      update_available: false,
    },
  });

  assert.equal(resolution.phase, 'no_update');
  assert.equal(resolution.message, 'Ya estás en la última versión (1.1.0).');
  assert.deepEqual(resolution.toast, {
    level: 'success',
    message: 'Ya estás en la última versión (1.1.0).',
  });
});

test('desktop native failure surfaces error when fallback is unavailable', () => {
  const resolution = resolveUpdateCheckState({
    runtime: 'desktop',
    appVersion: '1.1.0',
    nativeErrorDetail: 'network timeout',
    fallbackStatus: null,
  });

  assert.equal(resolution.phase, 'error');
  assert.equal(resolution.message, 'network timeout');
  assert.deepEqual(resolution.toast, {
    level: 'error',
    message: 'network timeout',
  });
});
