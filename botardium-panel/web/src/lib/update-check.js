/**
 * @typedef {'idle' | 'checking' | 'available' | 'downloading' | 'installing' | 'no_update' | 'fallback' | 'error'} NativeUpdatePhase
 */

/**
 * @typedef {{
 *   ok: boolean;
 *   current_version: string;
 *   latest_version?: string;
 *   update_available?: boolean;
 *   download_url?: string;
 *   release_url?: string;
 *   notes?: string;
 *   detail?: string;
 * }} UpdateStatus
 */

/**
 * @typedef {{ version: string; body?: string | null }} NativeUpdatePayload
 */

/**
 * @typedef {{ version: string; notes?: string }} NativeUpdateMeta
 */

/**
 * @typedef {{ level: 'success' | 'warning' | 'error'; message: string }} UpdateToast
 */

/**
 * @typedef {{ level: 'info' | 'warn'; event: string; payload: Record<string, unknown> }} UpdateLog
 */

/**
 * @typedef {{
 *   phase: NativeUpdatePhase;
 *   message: string;
 *   nativeUpdateMeta: NativeUpdateMeta | null;
 *   keepNativeUpdate: boolean;
 *   toast: UpdateToast | null;
 *   log: UpdateLog | null;
 * }} UpdateCheckResolution
 */

/**
 * @param {string} message
 * @returns {UpdateCheckResolution}
 */
const buildErrorResolution = (message) => ({
  phase: 'error',
  message,
  nativeUpdateMeta: null,
  keepNativeUpdate: false,
  toast: { level: 'error', message },
  log: null,
});

/**
 * @param {{
 *   runtime: 'browser' | 'desktop_error';
 *   appVersion: string;
 *   fallbackStatus?: UpdateStatus | null;
 *   nativeErrorDetail?: string;
 * }} input
 * @returns {UpdateCheckResolution}
 */
const resolveFallbackStatus = ({ runtime, appVersion, fallbackStatus, nativeErrorDetail }) => {
  if (!fallbackStatus?.ok) {
    return buildErrorResolution(
      nativeErrorDetail || fallbackStatus?.detail || 'No pude consultar actualizaciones.',
    );
  }

  if (fallbackStatus.update_available) {
    if (runtime === 'desktop_error') {
      return {
        phase: 'fallback',
        message: 'Modo compatibilidad activo: update manual disponible.',
        nativeUpdateMeta: null,
        keepNativeUpdate: false,
        toast: {
          level: 'warning',
          message: 'Updater nativo no disponible. Podés descargar el instalador manualmente.',
        },
        log: null,
      };
    }

    return {
      phase: 'fallback',
      message: 'Modo compatibilidad activo: update manual disponible.',
      nativeUpdateMeta: null,
      keepNativeUpdate: false,
      toast: {
        level: 'success',
        message: `Hay una actualización disponible: ${fallbackStatus.latest_version}.`,
      },
      log: { level: 'info', event: 'fallback_used', payload: { reason: 'not_desktop_runtime' } },
    };
  }

  const fallbackVersion = fallbackStatus.current_version || appVersion;
  return {
    phase: 'no_update',
    message: `Ya estás en la última versión (${fallbackVersion}).`,
    nativeUpdateMeta: null,
    keepNativeUpdate: false,
    toast: {
      level: 'success',
      message: `Ya estás en la última versión (${fallbackVersion}).`,
    },
    log: null,
  };
};

/**
 * Pure resolver for updater check decisions.
 * Mirrors the UI branches so they can be exercised without Tauri runtime.
 *
 * @param {{
 *   runtime: 'browser' | 'desktop';
 *   appVersion: string;
 *   nativeUpdate?: NativeUpdatePayload | null;
 *   nativeErrorDetail?: string;
 *   fallbackStatus?: UpdateStatus | null;
 * }} input
 * @returns {UpdateCheckResolution}
 */
export const resolveUpdateCheckState = ({
  runtime,
  appVersion,
  nativeUpdate = null,
  nativeErrorDetail,
  fallbackStatus = null,
}) => {
  if (runtime === 'desktop' && nativeErrorDetail) {
    return resolveFallbackStatus({
      runtime: 'desktop_error',
      appVersion,
      fallbackStatus,
      nativeErrorDetail,
    });
  }

  if (runtime === 'desktop') {
    if (nativeUpdate) {
      const normalizedNotes = String(nativeUpdate.body || '').trim();
      return {
        phase: 'available',
        message: `Update nativo disponible: ${nativeUpdate.version}.`,
        nativeUpdateMeta: {
          version: nativeUpdate.version,
          notes: normalizedNotes || undefined,
        },
        keepNativeUpdate: true,
        toast: { level: 'success', message: `Hay una actualización disponible: ${nativeUpdate.version}.` },
        log: { level: 'info', event: 'update_available', payload: { version: nativeUpdate.version } },
      };
    }

    return {
      phase: 'no_update',
      message: `Ya estás en la última versión (${appVersion}).`,
      nativeUpdateMeta: null,
      keepNativeUpdate: false,
      toast: { level: 'success', message: `Ya estás en la última versión (${appVersion}).` },
      log: { level: 'info', event: 'check_ok', payload: { update_available: false } },
    };
  }

  return resolveFallbackStatus({ runtime: 'browser', appVersion, fallbackStatus });
};
