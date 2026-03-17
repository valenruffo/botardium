
import { useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { open as openExternal } from "@tauri-apps/plugin-shell";
import { open as openFileDialog } from "@tauri-apps/plugin-dialog";
import { MagicBox } from "@/components/magic-box";
import { apiFetch, apiUrl, clearStoredSession, getStoredSession, setStoredSession, type StoredSession } from "@/lib/api";
import { Activity, Users, MessageSquare, ShieldAlert, Settings, LogOut, LogIn, ChevronDown, Loader2, Check, KeyRound, BookOpen, Sparkles, FolderKanban, BadgeCheck, SwitchCamera, Plus, Trash2 } from "lucide-react";

declare const __APP_VERSION__: string;
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuSubContent,
  DropdownMenuPortal,
} from "@/components/ui/dropdown-menu";

const fetcher = async (url: string) => {
  const res = await apiFetch(url);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `API error ${res.status}`);
  }
  return res.json();
};

const DEFAULT_MASTER_PROMPT = 'Mantén un tono profesional y humano para Instagram DM B2B. Prioriza claridad, cercanía y una CTA suave; evita frases agresivas o robóticas.';
const BRAND_LOGO_SRC = './logo.png';

type Lead = {
  id?: number;
  username: string;
  status: string;
  full_name?: string | null;
  bio?: string | null;
  campaign_id?: string | null;
  source?: string | null;
  timestamp?: string;
  contacted_at?: string | null;
  last_message_preview?: string | null;
  message_prompt?: string | null;
  message_variant?: string | null;
  last_message_rationale?: string | null;
  sent_at?: string | null;
  follow_up_due_at?: string | null;
  last_outreach_result?: string | null;
  last_outreach_error?: string | null;
  ig_account_id?: number | null;
};

type MessagePreview = {
  id: number;
  username: string;
  message: string;
  status?: string;
  rationale?: string;
  variant?: string;
  quality_flags?: string[];
};

type SelectOption = {
  value: string;
  label: string;
};

const formatSourceLabel = (source?: string | null) => {
  if (!source) return '-';
  if (source.startsWith('hashtag_')) return `#${source.replace('hashtag_', '')}`;
  if (source.startsWith('followers_')) return `@${source.replace('followers_', '')}`;
  if (source.startsWith('location_')) return `Ubicación: ${source.replace('location_', '')}`;
  return source.replaceAll('_', ' ');
};

const formatRejectionReason = (reason: string) => {
  const map: Record<string, string> = {
    hashtag_no_encontrado: 'Hashtag no encontrado',
    hashtag_muy_reducido: 'Hashtag muy reducido',
    hashtag_sin_posts_visibles: 'Hashtag sin posts visibles',
    pagina_hashtag_no_verificada: 'Página de hashtag no verificada',
    sin_match_nicho: 'Sin match de nicho',
    sin_posts_visibles: 'Sin posts visibles',
    autor_no_detectado: 'Autor no detectado',
    perfil_no_legible: 'Perfil no legible',
    baja_audiencia: 'Audiencia muy baja',
    baja_actividad: 'Actividad muy baja',
    sin_identidad: 'Sin identidad valida',
    sin_senales: 'Sin señales de nicho',
    perfil_fuera_nicho: 'Perfil fuera de nicho',
    keyword_excluida: 'Keyword excluida',
    privada: 'Cuenta privada',
    duplicado: 'Duplicado',
    post_no_legible: 'Post no legible',
  };
  return map[reason] || reason.replaceAll('_', ' ');
};

const isTauriDesktop = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

const openInstagramProfile = async (username: string) => {
  const profileUrl = `https://www.instagram.com/${username}/`;

  try {
    if (isTauriDesktop()) {
      await openExternal(profileUrl);
      return;
    }

    window.open(profileUrl, "_blank", "noopener,noreferrer");
  } catch {
    toast.error("No pude abrir el perfil en el navegador.");
  }
};

const cleanOperatorMessage = (message?: string | null) => {
  const raw = String(message || '').trim();
  if (!raw) return '';
  return raw
    .replace(/\b[A-Za-z_]*Error:\s*/g, '')
    .replace(/\|/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
};

const normalizeLeadDraftPreview = (message?: string | null) => {
  const raw = String(message || '').trim();
  if (!raw) return '';
  if (/todav[ií]a no hay borrador generado para este lead\.?/i.test(raw)) return '';
  return raw;
};

const buildCampaignDisplayName = (campaignName?: string | null, username?: string | null, sources?: Array<{ type: string; value?: string; target?: string }> | Array<{ type: string; target: string }>, fallbackId?: string | null) => {
  const cleanName = String(campaignName || '').trim();
  if (cleanName) return cleanName;
  const firstSource = Array.isArray(sources) ? sources[0] : null;
  const firstValue = firstSource ? String((firstSource as { value?: string; target?: string }).value || (firstSource as { value?: string; target?: string }).target || '').trim() : '';
  if (username && firstValue) return `@${username} · ${firstValue}`;
  if (username) return `@${username}`;
  return fallbackId ? `Campaña ${fallbackId.slice(0, 8)}` : 'Campaña sin nombre';
};

const HoverText = ({ text, className = '', children }: { text: string; className?: string; children?: React.ReactNode }) => (
  <div className={`group relative ${className}`}>
    {children ?? <span className="block max-w-full truncate">{text}</span>}
    <div className="pointer-events-none invisible absolute left-0 top-full z-30 mt-2 w-max max-w-[280px] rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs normal-case text-slate-200 opacity-0 shadow-xl transition-all group-hover:visible group-hover:opacity-100">
      {text}
    </div>
  </div>
);

const HoverBlock = ({ text, children, className = '' }: { text: string; children: React.ReactNode; className?: string }) => (
  <div className={`group relative ${className}`}>
    {children}
    <div className="pointer-events-none invisible absolute left-0 top-full z-30 mt-2 w-max max-w-[320px] rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs normal-case leading-relaxed text-slate-200 opacity-0 shadow-xl transition-all group-hover:visible group-hover:opacity-100">
      {text}
    </div>
  </div>
);

const GlowCheckbox = ({
  checked,
  onChange,
  ariaLabel,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  ariaLabel: string;
}) => (
  <button
    type="button"
    role="checkbox"
    aria-checked={checked}
    aria-label={ariaLabel}
    onClick={() => onChange(!checked)}
    className={`inline-flex h-5 w-5 items-center justify-center rounded-md border transition-all focus:outline-none focus:ring-2 focus:ring-cyan-400/60 ${checked ? 'border-cyan-400 bg-gradient-to-br from-cyan-400 to-emerald-400 text-slate-950 shadow-[0_0_18px_rgba(34,211,238,0.25)]' : 'border-slate-700 bg-slate-950 text-transparent hover:border-cyan-500/60 hover:bg-slate-900'}`}
  >
    <Check className={`h-3.5 w-3.5 transition-transform ${checked ? 'scale-100' : 'scale-75'}`} />
  </button>
);

const formatSourceStatusLabel = (status: string) => {
  if (status === 'done') return 'OK';
  if (status === 'running') return 'En curso';
  if (status === 'invalid') return 'Revisar';
  if (status === 'error') return 'Error';
  return status;
};

const formatCampaignStatusLabel = (status: ActiveCampaign['status']) => {
  if (status === 'draft') return 'Lista para lanzar';
  if (status === 'warmup') return 'Warmup en curso';
  if (status === 'ready') return 'Lista para scrapear';
  if (status === 'paused') return 'Pausada';
  if (status === 'needs_review') return 'Revisar fuentes';
  if (status === 'completed') return 'Pipeline completado';
  return 'Scraping corriendo';
};

const formatCampaignLog = (message: string) => {
  const safe = cleanOperatorMessage(message);
  if (safe.startsWith('Fuente descartada:')) {
    return { tone: 'warn', title: 'Fuente descartada', detail: safe.replace('Fuente descartada:', '').trim() };
  }
  if (safe.startsWith('Fuente completada:')) {
    return { tone: 'ok', title: 'Fuente completada', detail: safe.replace('Fuente completada:', '').trim() };
  }
  if (safe.includes('No se encontraron fuentes válidas')) {
    return { tone: 'warn', title: 'Revisar hashtags', detail: safe };
  }
  if (safe.startsWith('Ejecutando extractor real sobre')) {
    return { tone: 'info', title: 'Extracción iniciada', detail: safe.replace('Ejecutando extractor real sobre', '').trim() };
  }
  return { tone: 'info', title: 'Evento', detail: safe };
};

type MessageJob = {
  id: string;
  kind?: string;
  status: string;
  progress: number;
  campaign_id?: string | null;
  prompt: string;
  created_at: number;
  current_action: string;
  total: number;
  processed: number;
  current_lead?: string | null;
  eta_seconds?: number | null;
  eta_min_seconds?: number | null;
  eta_max_seconds?: number | null;
  metrics?: Record<string, number>;
  logs: { message: string; timestamp: number }[];
};

const formatDuration = (seconds: number) => {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rem = minutes % 60;
  return rem === 0 ? `${hours} h` : `${hours}h ${rem}m`;
};

const formatDurationRange = (minSeconds?: number | null, maxSeconds?: number | null) => {
  if (typeof minSeconds !== 'number' || typeof maxSeconds !== 'number' || minSeconds <= 0 || maxSeconds <= 0) return 'Tiempo estimado: --';
  const clampedMin = Math.max(1, minSeconds);
  const clampedMax = Math.max(clampedMin, maxSeconds);
  return `Tiempo estimado: ${formatDuration(clampedMin)} - ${formatDuration(clampedMax)}`;
};

const estimateSendEtaRangeSeconds = (leadCount: number, activeAccountId?: number | null, leads: Lead[] = []) => {
  if (leadCount <= 0) return { min: 0, max: 0 };
  let minPerLead = 120 + 35;
  let maxPerLead = 480 + 70;

  if (typeof activeAccountId === 'number' && leads.length > 0) {
    const sentDates = leads
      .filter((lead) => lead.ig_account_id === activeAccountId && lead.sent_at)
      .map((lead) => Date.parse(String(lead.sent_at)))
      .filter((ts) => Number.isFinite(ts))
      .sort((a, b) => a - b);
    const gaps: number[] = [];
    for (let i = 1; i < sentDates.length; i += 1) {
      const gap = Math.round((sentDates[i] - sentDates[i - 1]) / 1000);
      if (gap >= 20 && gap <= 1800) gaps.push(gap);
    }
    if (gaps.length >= 4) {
      const sorted = [...gaps].sort((a, b) => a - b);
      const p25 = sorted[Math.floor((sorted.length - 1) * 0.25)];
      const p75 = sorted[Math.floor((sorted.length - 1) * 0.75)];
      minPerLead = Math.max(60, Math.min(900, p25));
      maxPerLead = Math.max(minPerLead + 15, Math.min(1400, p75));
    }
  }

  return { min: leadCount * minPerLead, max: leadCount * maxPerLead };
};

const estimateWarmupRangeSeconds = (accountType?: string) => {
  const normalized = (accountType || 'mature').toLowerCase();
  if (normalized === 'mature') return { min: 8 * 60, max: 12 * 60 };
  if (normalized === 'new') return { min: 15 * 60, max: 25 * 60 };
  return { min: 12 * 60, max: 20 * 60 };
};

const formatJobStatusLabel = (status: string) => {
  if (status === 'completed') return 'Completado';
  if (status === 'running') return 'En curso';
  if (status === 'queued') return 'En cola';
  if (status === 'error') return 'Error';
  return status;
};

const CRM_STATUS_OPTIONS = [
  'Pendiente',
  'Listo para contactar',
  'Primer contacto',
  'Follow-up 1',
  'Follow-up 2',
  'Completado',
  'Respondio',
  'Calificado',
  'No responde',
  'No interesado',
  'Error',
] as const;

const getLeadStatusTone = (status: string) => {
  if (status === 'Pendiente' || status === 'Listo para contactar') return 'border-amber-500/30 text-amber-300';
  if (status === 'Primer contacto' || status === 'Follow-up 1' || status === 'Follow-up 2') return 'border-cyan-500/30 text-cyan-300';
  if (status === 'Respondio' || status === 'Calificado' || status === 'Completado') return 'border-emerald-500/30 text-emerald-300';
  if (status === 'No responde' || status === 'No interesado') return 'border-slate-500/30 text-slate-300';
  if (status.startsWith('Error')) return 'border-rose-500/30 text-rose-300';
  return 'border-rose-500/30 text-rose-300';
};

function GlowSelect({
  value,
  onChange,
  options,
  disabled = false,
  size = 'sm',
  className = '',
}: {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  disabled?: boolean;
  size?: 'xs' | 'sm' | 'md';
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onEscape);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onEscape);
    };
  }, []);

  const active = options.find((opt) => opt.value === value);
  const py = size === 'xs' ? 'py-1' : size === 'md' ? 'py-2.5' : 'py-1.5';
  const text = size === 'xs' ? 'text-[11px]' : size === 'md' ? 'text-sm' : 'text-xs';

  return (
    <div ref={rootRef} className={`relative ${className}`}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((prev) => !prev)}
        className={`w-full rounded-xl border border-slate-700 bg-slate-950/90 px-3 ${py} pr-9 text-left ${text} text-slate-100 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] outline-none transition-all hover:border-slate-500 focus:border-cyan-500 disabled:cursor-not-allowed disabled:opacity-40`}
      >
        <span className="block truncate">{active?.label || value}</span>
      </button>
      <ChevronDown className={`pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`} />
      {open && !disabled && (
        <div className="absolute left-0 right-0 z-50 mt-1 overflow-hidden rounded-xl border border-cyan-500/30 bg-slate-950 shadow-2xl shadow-cyan-900/20">
          <div className="max-h-64 overflow-y-auto py-1">
            {options.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => {
                  onChange(option.value);
                  setOpen(false);
                }}
                className={`block w-full px-3 py-2 text-left ${text} transition-colors ${option.value === value ? 'bg-cyan-500/20 text-cyan-100' : 'text-slate-200 hover:bg-slate-800 hover:text-white'}`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

type IgAccount = {
  id: number;
  ig_username: string;
  session_status?: string;
  warmup_status?: 'idle' | 'running' | 'ready' | 'error';
  warmup_progress?: number;
  warmup_last_run_at?: string | null;
  warmup_last_duration_min?: number;
  warmup_required?: boolean;
  health_score?: number;
  current_action?: string;
  last_error?: string;
  daily_dm_limit?: number;
  daily_dm_sent?: number;
  is_busy?: boolean;
  account_type?: 'mature' | 'new' | 'rehab';
  account_warmup_status?: string;
  account_warmup_days_total?: number;
  account_warmup_days_completed?: number;
  session_warmup_last_run_at?: string | null;
  session_warmup_phase?: string;
  requires_session_warmup?: boolean;
  requires_account_warmup?: boolean;
};

type ApiError = {
  detail?: string;
};

type StrategyResult = {
  sources: Array<{
    type: 'hashtag' | 'followers' | 'location';
    target: string;
  }>;
  reasoning: string;
  filter_context?: {
    intent_summary?: string;
    include_terms?: string[];
    exclude_terms?: string[];
  };
};

type CampaignDraft = {
  name: string;
  sources: Array<StrategyResult['sources'][number]>;
  strategyContext?: StrategyResult['filter_context'];
  limit: number;
  executionMode: 'real' | 'test';
  minFollowers: number;
  minPosts: number;
  requireCoherence: boolean;
};

type ActiveCampaign = {
  id: string;
  campaignName: string;
  username: string;
  limit: number;
  status: 'draft' | 'warmup' | 'ready' | 'paused' | 'needs_review' | 'running' | 'completed';
  currentAction: string;
  sources: Array<StrategyResult['sources'][number]>;
  createdAt: number;
  executionMode: 'real' | 'test';
  filterProfile: 'strict' | 'balanced' | 'expansive';
  progress: number;
  logs: { message: string; timestamp: number }[];
  sourceStats: Record<string, { accepted: number; rejected: Record<string, number>; status: string; posts_seen?: number; authors_seen?: number; profile_errors?: number; error?: string }>;
  filters?: {
    filter_profile?: ActiveCampaign['filterProfile'];
    min_followers?: number;
    min_posts?: number;
    require_identity?: boolean;
    require_keyword_match?: boolean;
    require_coherence?: boolean;
  };
};

type Workspace = {
  id: number;
  name: string;
  slug: string;
};

// Ordenar workspaces: el actual primero, luego por nombre
const sortWorkspaces = (workspaces: Workspace[], currentId?: number | null): Workspace[] => {
  return [...workspaces].sort((a, b) => {
    if (a.id === currentId) return -1;
    if (b.id === currentId) return 1;
    return a.name.localeCompare(b.name);
  });
};

type WorkspaceDeleteButtonProps = {
  workspaceId: number;
  workspaceName: string;
  onDeleted: () => Promise<boolean>;
  disabled?: boolean;
};

function WorkspaceDeleteButton({ workspaceId, workspaceName, onDeleted, disabled }: WorkspaceDeleteButtonProps) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const deleteAttemptRef = useRef(0);
  
  useEffect(() => {
    if (confirming && !deleting) {
      const timer = setTimeout(() => setConfirming(false), 3000);
      return () => clearTimeout(timer);
    }
  }, [confirming, deleting]);
  
  const handleDelete = async () => {
    if (disabled || deleting) return;

    if (!confirming) {
      setConfirming(true);
      return;
    }
    
    const attemptId = ++deleteAttemptRef.current;
    setDeleting(true);
    
    try {
      console.log(`[WorkspaceDelete] Attempt ${attemptId}: Starting delete for workspace ${workspaceId}`);
      
      const res = await apiFetch(apiUrl(`/api/workspaces/${workspaceId}`), { 
        method: 'DELETE',
      });
      
      console.log(`[WorkspaceDelete] Attempt ${attemptId}: Response status ${res.status}`);
      
      if (attemptId !== deleteAttemptRef.current) {
        console.log(`[WorkspaceDelete] Attempt ${attemptId}: Cancelled by newer attempt`);
        return;
      }
      
      if (res.ok) {
        console.log(`[WorkspaceDelete] Attempt ${attemptId}: Success response`);
        const removed = await onDeleted();
        if (removed) {
          toast.success(`Workspace "${workspaceName}" eliminado.`);
        } else {
          toast.error('El workspace no se reflejo en la UI. Reintentando sincronizar...');
        }
      } else {
        const data = await res.json();
        const errMsg = data.detail || `Error ${res.status}: No pude eliminar el workspace`;
        console.error(`[WorkspaceDelete] Attempt ${attemptId}: Error -`, errMsg);
        toast.error(errMsg);
        setConfirming(false);
      }
    } catch (err) {
      if (attemptId !== deleteAttemptRef.current) {
        console.log(`[WorkspaceDelete] Attempt ${attemptId}: Cancelled by newer attempt`);
        return;
      }

      const msg = err instanceof Error ? err.message : 'Error de conexión';
      console.error(`[WorkspaceDelete] Attempt ${attemptId}: Exception -`, msg);

      await new Promise((resolve) => setTimeout(resolve, 1200));
      const removed = await onDeleted();
      if (removed) {
        toast.success(`Workspace "${workspaceName}" eliminado.`);
      } else {
        toast.error(msg);
      }
      setConfirming(false);
    }
    setDeleting(false);
  };
  
  const isDisabled = disabled || deleting;
  
  return (
    <button
      type="button"
      onClick={handleDelete}
      onBlur={() => !deleting && setConfirming(false)}
      disabled={isDisabled}
      className={`opacity-0 group-hover:opacity-100 p-2 rounded-lg transition-all ${
        isDisabled
          ? 'opacity-100 bg-slate-600 cursor-wait'
          : confirming 
            ? 'opacity-100 bg-rose-500 text-white hover:bg-rose-600' 
            : 'text-rose-400 hover:bg-rose-500/20'
      }`}
      title={deleting ? 'Eliminando...' : confirming ? 'Clickeá de nuevo para confirmar' : 'Eliminar workspace'}
    >
      {deleting ? (
        <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
      ) : confirming ? (
        <Check className="w-4 h-4" />
      ) : (
        <Trash2 className="w-4 h-4" />
      )}
    </button>
  );
}

type AiSettingsStatus = {
  google_api_key: string;
  openai_api_key: string;
  google_configured: boolean;
  openai_configured: boolean;
  magic_box_enabled: boolean;
  message_studio_enabled: boolean;
  lead_drafts_enabled: boolean;
  recommended_provider?: 'google' | 'openai' | null;
  google_label: string;
  openai_label: string;
};

type UpdateStatus = {
  ok: boolean;
  current_version: string;
  latest_version?: string;
  update_available?: boolean;
  download_url?: string;
  release_url?: string;
  notes?: string;
  detail?: string;
};

export default function Dashboard() {
  const [currentRoute, setCurrentRoute] = useState<'auth' | 'register' | 'accounts' | 'app'>('auth');
  const [currentView, setCurrentView] = useState<'dashboard' | 'crm' | 'campaigns' | 'message_studio' | 'guide' | 'api_keys' | 'admin_accounts'>('dashboard');
  const [isWorkspaceSessionExpired, setIsWorkspaceSessionExpired] = useState(false);

  useEffect(() => {
    const handleExpired = () => setIsWorkspaceSessionExpired(true);
    window.addEventListener('botardium-session-expired', handleExpired);
    return () => window.removeEventListener('botardium-session-expired', handleExpired);
  }, []);

  // Auth Form State
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [registerFullName, setRegisterFullName] = useState("");
  const [newWorkspaceName, setNewWorkspaceName] = useState("");
  const [googleApiKeyInput, setGoogleApiKeyInput] = useState("");
  const [openAiApiKeyInput, setOpenAiApiKeyInput] = useState("");
  const [isSavingAiKeys, setIsSavingAiKeys] = useState(false);
  const [isCheckingUpdates, setIsCheckingUpdates] = useState(false);
  const [isExportingWorkspace, setIsExportingWorkspace] = useState(false);
  const [isImportingWorkspace, setIsImportingWorkspace] = useState(false);
  const [currentUserId, setCurrentUserId] = useState<number | null>(null);
  const [currentUserEmail, setCurrentUserEmail] = useState("");

  // IG Account State
  const [isLoggingIn, setIsLoggingIn] = useState(false);
  const [campaignDraft, setCampaignDraft] = useState<CampaignDraft>({
    name: '',
    sources: [{ type: 'followers', target: '' }],
    strategyContext: undefined,
    limit: 5,
    executionMode: 'real',
    minFollowers: 50,
    minPosts: 3,
    requireCoherence: true,
  });
  const [lastStrategy, setLastStrategy] = useState<StrategyResult | null>(null);
  const [selectedLeadIds, setSelectedLeadIds] = useState<number[]>([]);
  const [crmFilter, setCrmFilter] = useState<'all' | 'pending' | 'contacting' | 'qualified' | 'error'>('all');
  const [selectedCampaignFilter, setSelectedCampaignFilter] = useState<string | null>(null);
  const [messagePrompt, setMessagePrompt] = useState('Te ayudo a abrir conversaciones reales con potenciales clientes desde Instagram para tu negocio.');
  const [followUp1Prompt, setFollowUp1Prompt] = useState('Retoma la conversación con naturalidad, sin sonar insistente, y deja una pregunta simple para reabrir el tema.');
  const [followUp2Prompt, setFollowUp2Prompt] = useState('Haz un último seguimiento breve, amable y sin presión, dejando una salida elegante si no le interesa.');
  const [masterPromptMode, setMasterPromptMode] = useState<'default' | 'custom'>('default');
  const [masterPrompt, setMasterPrompt] = useState(DEFAULT_MASTER_PROMPT);
  const [messagePreviews, setMessagePreviews] = useState<MessagePreview[]>([]);
  const [selectedLeadDraft, setSelectedLeadDraft] = useState<Lead | null>(null);
  const [leadDraftText, setLeadDraftText] = useState('');
  const [showSessionWarmupModal, setShowSessionWarmupModal] = useState(false);
  const [isPreparingDrafts, setIsPreparingDrafts] = useState(false);
  const [isSavingDrafts, setIsSavingDrafts] = useState(false);
  const [draftProgressLabel, setDraftProgressLabel] = useState('');
  const [expandedCampaigns, setExpandedCampaigns] = useState<Record<string, boolean>>({});
  const [editingCampaignId, setEditingCampaignId] = useState<string | null>(null);
  const [editingCampaignName, setEditingCampaignName] = useState('');
  const [bulkStatusSelection, setBulkStatusSelection] = useState<string>('Listo para contactar');
  const [pendingSendIds, setPendingSendIds] = useState<number[] | null>(null);
  const [isReloggingAccount, setIsReloggingAccount] = useState(false);
  const [messageStatuses, setMessageStatuses] = useState<Array<'Pendiente' | 'Listo para contactar' | 'Primer contacto' | 'Follow-up 1' | 'Follow-up 2'>>(['Pendiente', 'Listo para contactar', 'Primer contacto', 'Follow-up 1', 'Follow-up 2']);
  const [messageScopeCampaign, setMessageScopeCampaign] = useState<string>('');
  const [campaignDeleteConfirming, setCampaignDeleteConfirming] = useState<Record<string, boolean>>({});
  const [campaignDeleteLoading, setCampaignDeleteLoading] = useState<Record<string, boolean>>({});
  const campaignDeleteConfirmTimeouts = useRef<Record<string, number>>({});
  const openHowTo = () => {
    setCurrentRoute('app');
    setCurrentView('guide');
  };
  const openApiKeys = () => {
    setCurrentRoute('app');
    setCurrentView('api_keys');
  };

  useEffect(() => {
    return () => {
      Object.values(campaignDeleteConfirmTimeouts.current).forEach((timeoutId) => {
        window.clearTimeout(timeoutId);
      });
    };
  }, []);

  const clearCampaignDeleteConfirm = (campaignId: string) => {
    const existingTimeout = campaignDeleteConfirmTimeouts.current[campaignId];
    if (existingTimeout) {
      window.clearTimeout(existingTimeout);
      delete campaignDeleteConfirmTimeouts.current[campaignId];
    }
    setCampaignDeleteConfirming((prev) => {
      if (!prev[campaignId]) return prev;
      const next = { ...prev };
      delete next[campaignId];
      return next;
    });
  };

  const armCampaignDeleteConfirm = (campaignId: string) => {
    clearCampaignDeleteConfirm(campaignId);
    setCampaignDeleteConfirming((prev) => ({ ...prev, [campaignId]: true }));
    campaignDeleteConfirmTimeouts.current[campaignId] = window.setTimeout(() => {
      setCampaignDeleteConfirming((prev) => {
        if (!prev[campaignId]) return prev;
        const next = { ...prev };
        delete next[campaignId];
        return next;
      });
      delete campaignDeleteConfirmTimeouts.current[campaignId];
    }, 3200);
  };

  const syncCampaignDeletion = async (campaignId: string): Promise<boolean> => {
    const updated = await mutateBotStatus();
    const latestCampaigns = updated?.campaigns || [];
    return !latestCampaigns.some((campaign) => campaign.id === campaignId);
  };
  const applySession = (session: StoredSession) => {
    setStoredSession(session);
    setCurrentUserId(session.workspace_id);
    setCurrentUserEmail(session.workspace_name);
    setCurrentRoute('accounts');
  };

  const closeSession = () => {
    setCurrentUserId(null);
    setCurrentUserEmail('');
    clearStoredSession();
    setCurrentRoute('auth');
  };

  const loginToWorkspace = async (workspaceId: number, fallbackName?: string) => {
    const res = await apiFetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: workspaceId }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data?.auth?.token) {
      throw new Error(data.detail || 'No pude abrir la sesión local del workspace.');
    }
    applySession(data.auth as StoredSession);
    toast.success(`Workspace ${(data.auth?.workspace_name || fallbackName || 'local')} cargado.`);
  };

  // Data Fetching
  const workspaceQuery = currentUserId ? `workspace_id=${encodeURIComponent(String(currentUserId))}` : '';
  const leadsEndpoint = currentRoute === 'app' && currentUserId
    ? apiUrl(`/api/leads?${workspaceQuery}${selectedCampaignFilter ? `&campaign_id=${encodeURIComponent(selectedCampaignFilter)}` : ''}`)
    : null;
  const { data: leads, mutate: mutateLeads } = useSWR<Lead[] | { leads?: Lead[] }>(leadsEndpoint, fetcher, { refreshInterval: 2000 });
  const { data: igAccountsData, mutate: mutateAccounts } = useSWR<IgAccount[]>(currentUserId ? apiUrl(`/api/accounts?workspace_id=${currentUserId}`) : null, fetcher, { refreshInterval: 2000 });
  const { data: workspacesData, mutate: mutateWorkspaces } = useSWR<{ workspaces: Workspace[] }>(apiUrl('/api/workspaces'), fetcher, { refreshInterval: 0 });
  const { data: aiSettings, mutate: mutateAiSettings } = useSWR<AiSettingsStatus>(currentUserId ? apiUrl(`/api/workspaces/${currentUserId}/ai-settings`) : null, fetcher, { refreshInterval: 0 });
  const { data: updateStatus, mutate: mutateUpdateStatus } = useSWR<UpdateStatus>(apiUrl(`/api/app/update-status?current_version=${encodeURIComponent(__APP_VERSION__)}`), fetcher, { refreshInterval: 15 * 60 * 1000, revalidateOnFocus: false });
  const { data: botStatus, mutate: mutateBotStatus } = useSWR<{
    is_running: boolean; campaigns: Array<{
      id: string;
      campaign_name?: string;
      username: string;
      limit: number;
      status: ActiveCampaign['status'] | 'completed';
      current_action: string;
      sources: { type: StrategyResult['sources'][number]['type']; value: string }[];
      source_stats: Record<string, { accepted: number; rejected: Record<string, number>; status: string; posts_seen?: number; authors_seen?: number; profile_errors?: number; error?: string }>;
      created_at: number;
      execution_mode: ActiveCampaign['executionMode'];
      filter_profile?: ActiveCampaign['filterProfile'];
      filters?: ActiveCampaign['filters'];
      progress: number;
      logs: { message: string; timestamp: number }[];
    }>
  }>(currentRoute === 'app' && currentUserId ? apiUrl(`/api/bot/status?workspace_id=${currentUserId}`) : null, fetcher, { refreshInterval: 2000 });
  const { data: messageJobsData, mutate: mutateMessageJobs } = useSWR<{ jobs: MessageJob[] }>(currentRoute === 'app' && currentUserId ? apiUrl(`/api/messages/jobs?workspace_id=${currentUserId}`) : null, fetcher, { refreshInterval: 2000 });

  const previousLeadsCount = useRef(0);
  const activeAccount = igAccountsData?.[0] ?? null;
  const activeWarmups = (igAccountsData || []).filter((account) => account.warmup_status === 'running');
  const aiBlockedReason = 'Necesitas API keys para usar funciones con IA. Configúralas en API Keys.';
  const hasAiForMessages = !!aiSettings?.message_studio_enabled;
  const hasAiForMagicBox = !!aiSettings?.magic_box_enabled;

  const requireAiFeature = (enabled: boolean, reason = aiBlockedReason) => {
    if (enabled) return true;
    toast.error(reason);
    openApiKeys();
    return false;
  };
  const messageJobsDataRaw = messageJobsData?.jobs || [];
  const messageJobs = messageJobsDataRaw.filter((job) => job.kind !== 'prepare');
  const activeCampaigns: ActiveCampaign[] = (botStatus?.campaigns || []).map((campaign) => ({
    id: campaign.id,
    campaignName: campaign.campaign_name || `@${campaign.username} · ${campaign.sources?.[0]?.value || campaign.id.slice(0, 8)}`,
    username: campaign.username,
    limit: campaign.limit,
    status: campaign.status,
    currentAction: campaign.current_action,
    sources: campaign.sources.map((source) => ({ type: source.type, target: source.value })),
    createdAt: campaign.created_at,
    executionMode: campaign.execution_mode,
    filterProfile: campaign.filter_profile || 'strict',
    progress: campaign.progress,
    logs: campaign.logs,
    sourceStats: campaign.source_stats || {},
    filters: campaign.filters,
  }));
  const sortedCampaigns = useMemo(() => {
    const rank = (status: ActiveCampaign['status']) => {
      if (status === 'running' || status === 'warmup' || status === 'paused') return 0;
      if (status === 'needs_review') return 1;
      if (status === 'ready' || status === 'draft') return 2;
      return 3;
    };
    return [...activeCampaigns].sort((a, b) => {
      const diff = rank(a.status) - rank(b.status);
      if (diff !== 0) return diff;
      return b.createdAt - a.createdAt;
    });
  }, [activeCampaigns]);
  const campaignLabelById = useMemo(() => Object.fromEntries(activeCampaigns.map((campaign) => [campaign.id, campaign.campaignName])), [activeCampaigns]);
  const accountWarmupAction = async (accountId: number, action: 'start' | 'cancel', durationMin = 10) => {
    try {
      const endpoint = action === 'start'
        ? apiUrl(`/api/accounts/${accountId}/warmup`)
        : apiUrl(`/api/accounts/${accountId}/warmup-cancel`);
      const res = await apiFetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: action === 'start' ? JSON.stringify({ duration_min: durationMin }) : undefined,
      });
      const data = await res.json();
      if (!res.ok) {
        toast.error(data.detail || 'No pude actualizar el warmup de la cuenta.');
        return false;
      }
      const refreshed = await mutateAccounts();
      if (action === 'cancel') {
        toast.success('Warmup cancelado.');
        return true;
      }

      let latestAccount = (refreshed || igAccountsData || []).find((acc) => acc.id === accountId);
      if (latestAccount?.warmup_status === 'error') {
        toast.error(cleanOperatorMessage(latestAccount.last_error) || 'El warmup falló al iniciar. Revisa la sesión de la cuenta.');
        return false;
      }

      if (latestAccount?.warmup_status !== 'running') {
        for (let attempt = 0; attempt < 3; attempt += 1) {
          await new Promise((resolve) => setTimeout(resolve, 700));
          const poll = await mutateAccounts();
          latestAccount = (poll || igAccountsData || []).find((acc) => acc.id === accountId);
          if (latestAccount?.warmup_status === 'running') break;
          if (latestAccount?.warmup_status === 'error') {
            toast.error(cleanOperatorMessage(latestAccount.last_error) || 'El warmup falló al iniciar. Revisa la sesión de la cuenta.');
            return false;
          }
        }
      }

      if (latestAccount?.warmup_status === 'running') {
        await new Promise((resolve) => setTimeout(resolve, 1200));
        const confirm = await mutateAccounts();
        latestAccount = (confirm || igAccountsData || []).find((acc) => acc.id === accountId);
        if (latestAccount?.warmup_status === 'error') {
          toast.error(cleanOperatorMessage(latestAccount.last_error) || 'El warmup arrancó pero falló al instante. Revisa la sesión de la cuenta.');
          return false;
        }
        toast.success('Calentamiento de sesión iniciado.');
      } else {
        toast.warning('No se pudo iniciar el calentamiento. Reintenta en unos segundos.');
      }
      return true;
    } catch {
      toast.error('Error conectando con el motor de warmup.');
      return false;
    }
  };

  const connectInstagramAccount = async (redirectToApp = false) => {
    if (!currentUserId) return;
    setIsLoggingIn(true);
    toast.loading('Iniciando navegador seguro. Por favor, inicia sesión en Instagram...', { id: 'login-ig' });
    try {
      const res = await apiFetch(apiUrl('/api/ig/login'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: currentUserId })
      });
      const raw = await res.text();
      let data: ApiError & Partial<IgAccount> = {};
      try {
        data = raw ? JSON.parse(raw) : {};
      } catch {
        data = { detail: raw || `Respuesta no valida del backend (${res.status}).` };
      }
      toast.dismiss('login-ig');
      if (res.ok) {
        toast.success(`✅ Cuenta @${data.ig_username} conectada exitosamente.`);
        mutateAccounts();
        if (redirectToApp) setCurrentRoute('app');
      } else {
        toast.error(data.detail || `Error al conectar la cuenta (${res.status}).`);
      }
    } catch (err) {
      toast.dismiss('login-ig');
      const message = err instanceof Error ? err.message : 'Fallo al iniciar el navegador.';
      toast.error(message);
    } finally {
      setIsLoggingIn(false);
    }
  };

  const warmupActiveSessionFromCrm = async () => {
    if (!activeAccount) {
      toast.error('Primero selecciona o conecta una cuenta emisora.');
      return;
    }
    if (activeAccount.requires_account_warmup) {
      toast.error('Esta cuenta todavía necesita calentamiento de cuenta de varios días. Hazlo desde Cuentas.');
      return;
    }
    if (selectedLeadIds.length > 0) {
      toast.info(`Calentamiento iniciado para preparar ${selectedLeadIds.length} lead(s). ${formatDurationRange(totalRangeForSelected.min, totalRangeForSelected.max)} incluyendo warmup + envío.`);
    }
    await accountWarmupAction(activeAccount.id, 'start', activeAccount.account_type === 'mature' ? 10 : 18);
  };

  const saveAiKeys = async () => {
    if (!currentUserId) return;
    try {
      setIsSavingAiKeys(true);
      const res = await apiFetch(apiUrl(`/api/workspaces/${currentUserId}/ai-settings`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          google_api_key: googleApiKeyInput,
          openai_api_key: openAiApiKeyInput,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        toast.error(data.detail || 'No pude guardar las API keys.');
        return;
      }
      await mutateAiSettings();
      setGoogleApiKeyInput('');
      setOpenAiApiKeyInput('');
      toast.success('API keys guardadas para este workspace.');
    } catch {
      toast.error('Error guardando las API keys.');
    } finally {
      setIsSavingAiKeys(false);
    }
  };

  const checkForUpdates = async () => {
    try {
      setIsCheckingUpdates(true);
      const data = await mutateUpdateStatus();
      if (!data?.ok) {
        toast.error(data?.detail || 'No pude consultar actualizaciones.');
        return;
      }
      if (data.update_available) {
        toast.success(`Hay una actualización disponible: ${data.latest_version}.`);
        return;
      }
      toast.success(`Ya estás en la última versión (${data.current_version}).`);
    } catch {
      toast.error('Error revisando actualizaciones.');
    } finally {
      setIsCheckingUpdates(false);
    }
  };

  const openUpdateDownload = async () => {
    if (!updateStatus?.download_url) {
      toast.error('No encontré un instalador publicado para descargar.');
      return;
    }
    await openExternal(updateStatus.download_url);
  };

  const exportWorkspace = async () => {
    if (!currentUserId) return;
    try {
      setIsExportingWorkspace(true);
      const res = await apiFetch(apiUrl(`/api/workspaces/${currentUserId}/export`), { method: 'POST' });
      const data = await res.json();
      if (!res.ok) {
        toast.error(data.detail || 'No pude exportar el workspace.');
        return;
      }
      toast.success(`Workspace exportado en ${data.path}`);
      await openExternal(data.path);
    } catch {
      toast.error('Error exportando el workspace.');
    } finally {
      setIsExportingWorkspace(false);
    }
  };

  const importWorkspace = async () => {
    try {
      setIsImportingWorkspace(true);
      const selected = await openFileDialog({
        multiple: false,
        filters: [{ name: 'Workspace export', extensions: ['zip'] }],
      });
      if (!selected || Array.isArray(selected)) return;
      const res = await apiFetch(apiUrl('/api/workspaces/import'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ zip_path: selected }),
      });
      const data = await res.json();
      if (!res.ok) {
        toast.error(data.detail || 'No pude importar el workspace.');
        return;
      }
      await mutateWorkspaces();
      if (data.auth?.token) {
        applySession(data.auth as StoredSession);
      }
      toast.success(`Workspace ${data.name} importado correctamente.`);
    } catch {
      toast.error('Error importando el workspace.');
    } finally {
      setIsImportingWorkspace(false);
    }
  };

  const reloginAccount = async (account: IgAccount) => {
    if (isReloggingAccount) return;
    try {
      setIsReloggingAccount(true);
      toast.info('Abriendo navegador para re-login manual de la cuenta.');
      const res = await apiFetch(apiUrl(`/api/accounts/${account.id}/relogin`), { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        toast.error(data.detail || 'No pude revalidar la sesión de la cuenta.');
        return;
      }
      await mutateAccounts();
      toast.success(`Sesión revalidada para @${account.ig_username}.`);
    } catch (error) {
      const reason = error instanceof Error ? error.message : 'Error en re-login de la cuenta.';
      toast.error(reason);
    } finally {
      setIsReloggingAccount(false);
    }
  };

  const reloginActiveAccount = () => {
    if (!activeAccount) {
      toast.error('Primero selecciona o conecta una cuenta emisora.');
      return;
    }
    return reloginAccount(activeAccount);
  };

  const sendSingleLead = async (lead?: Lead) => {
    if (!lead?.id) return;
    if (!activeAccount) {
      toast.error('Conecta o selecciona una cuenta emisora primero.');
      return;
    }
    if (activeAccount.requires_account_warmup) {
      toast.error('Esta cuenta todavía necesita calentamiento de cuenta de varios días.');
      return;
    }
    if (['Follow-up 2', 'Completado'].includes(lead.status)) {
      toast.info('Este lead ya completó la secuencia. No se enviarán más mensajes automáticos.');
      return;
    }
    if (!['Listo para contactar', 'Primer contacto', 'Follow-up 1'].includes(lead.status)) {
      toast.info(`@${lead.username} cambiado a "Listo para contactar" para poder enviar.`);
      await updateSingleLeadStatus(lead.id, 'Listo para contactar');
    }
    if (activeAccount.requires_session_warmup) {
      setPendingSendIds([lead.id]);
      setShowSessionWarmupModal(true);
      return;
    }
    await executeOutreachSend(false, [lead.id]);
  };

  const updateAccountType = async (accountId: number, accountType: 'mature' | 'new' | 'rehab') => {
    try {
      const res = await apiFetch(apiUrl(`/api/accounts/${accountId}/profile`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_type: accountType }),
      });
      const data = await res.json();
      if (!res.ok) {
        toast.error(data.detail || 'No pude actualizar el tipo de cuenta.');
        return;
      }
      await mutateAccounts();
      toast.success('Perfil de cuenta actualizado.');
    } catch {
      toast.error('Error actualizando el perfil de cuenta.');
    }
  };

  const completeAccountWarmupDay = async (accountId: number) => {
    try {
      const res = await apiFetch(apiUrl(`/api/accounts/${accountId}/account-warmup-day`), { method: 'POST' });
      const data = await res.json();
      if (!res.ok) {
        toast.error(data.detail || 'No pude registrar el avance de calentamiento.');
        return;
      }
      await mutateAccounts();
      toast.success(`Dia de calentamiento registrado (${data.completed_days}/${data.total_days}).`);
    } catch {
      toast.error('Error registrando el calentamiento de cuenta.');
    }
  };

  const InfoHint = ({ text }: { text: string }) => (
    <span className="group relative inline-flex">
      <button
        type="button"
        onClick={openHowTo}
        className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-slate-700 bg-slate-900 text-[11px] font-bold text-slate-300 hover:border-cyan-500 hover:text-cyan-300"
      >
        i
      </button>
      <span className="pointer-events-none absolute bottom-full left-1/2 z-30 mb-2 hidden w-64 -translate-x-1/2 rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-left text-[11px] font-normal leading-relaxed text-slate-300 shadow-2xl group-hover:block">
        {text}
      </span>
    </span>
  );

  const setSourceAt = (index: number, field: 'type' | 'target', value: string) => {
    setCampaignDraft((prev) => ({
      ...prev,
      sources: prev.sources.map((source, sourceIndex) => (
        sourceIndex === index
          ? {
            ...source,
            [field]: field === 'target' ? value.replace(/^[@#]/, '') : value,
          }
          : source
      )),
    }));
  };



  const campaignAction = async (campaignId: string, action: 'start_warmup' | 'finish_warmup' | 'start_scraping' | 'pause') => {
    try {
      const res = await apiFetch(apiUrl(`/api/bot/${campaignId}/action`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        toast.error(data.detail || 'Error modificando la campana.');
        if (res.status === 409) {
          await mutateAccounts(); // Refresh the session_status locally so the button becomes angry red
          setCurrentView('admin_accounts'); // Brutally kick the user back out
        }
        return;
      }
      await mutateBotStatus();
    } catch {
      toast.error('Error conectando con el estado de campanas.');
    }
  };

  const handleCampaignDelete = async (campaignId: string, campaignName: string) => {
    if (campaignDeleteLoading[campaignId]) return;
    if (!campaignDeleteConfirming[campaignId]) {
      armCampaignDeleteConfirm(campaignId);
      return;
    }

    clearCampaignDeleteConfirm(campaignId);
    setCampaignDeleteLoading((prev) => ({ ...prev, [campaignId]: true }));

    try {
      const res = await apiFetch(apiUrl(`/api/bot/${campaignId}/action`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'delete' }),
      });

      if (res.ok) {
        const removed = await syncCampaignDeletion(campaignId);
        if (removed) {
          toast.success(`Campana "${campaignName}" eliminada.`);
        } else {
          toast.error('La campana no se actualizo en pantalla. Reintentando sincronizar...');
        }
      } else {
        const data = await res.json().catch(() => ({}));
        toast.error(data.detail || 'No pude eliminar la campana.');
      }
    } catch (error) {
      await new Promise((resolve) => setTimeout(resolve, 1200));
      const removed = await syncCampaignDeletion(campaignId);
      if (removed) {
        toast.success(`Campana "${campaignName}" eliminada.`);
      } else {
        const message = error instanceof Error ? error.message : 'Error conectando con el estado de campanas.';
        toast.error(message);
      }
    } finally {
      setCampaignDeleteLoading((prev) => {
        if (!prev[campaignId]) return prev;
        const next = { ...prev };
        delete next[campaignId];
        return next;
      });
    }
  };

  const saveCampaignName = async (campaignId: string) => {
    const nextName = editingCampaignName.trim();
    if (!nextName) {
      toast.error('Escribe un nombre de campaña.');
      return;
    }
    try {
      const res = await apiFetch(apiUrl(`/api/bot/${campaignId}/action`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'rename', campaign_name: nextName }),
      });
      const data = await res.json();
      if (!res.ok) {
        toast.error(data.detail || 'No pude renombrar la campaña.');
        return;
      }
      setEditingCampaignId(null);
      setEditingCampaignName('');
      await mutateBotStatus();
      toast.success('Nombre de campaña actualizado.');
    } catch {
      toast.error('Error guardando el nombre de campaña.');
    }
  };

  // Sonner Hook on new leads
  useEffect(() => {
    const session = getStoredSession();
    if (!session) return;
    applySession(session);
    apiFetch('/api/auth/session')
      .then(async (res) => {
        if (!res.ok) throw new Error('invalid-session');
        const data = await res.json();
        if (!data?.workspace_id) throw new Error('invalid-session');
      })
      .catch(() => {
        closeSession();
        toast.info('La sesión local expiró. Vuelve a abrir tu workspace.');
      });
  }, []);

  useEffect(() => {
    setGoogleApiKeyInput('');
    setOpenAiApiKeyInput('');
  }, [currentUserId]);

  // Sonner Hook on new leads
  useEffect(() => {
    const leadsArray = Array.isArray(leads) ? leads : (leads?.leads || []);
    if (leadsArray.length > 0) {
      if (previousLeadsCount.current > 0 && leadsArray.length > previousLeadsCount.current) {
        const newLeads = leadsArray.length - previousLeadsCount.current;
        toast.success(`¡Mina de oro! ${newLeads} lead(s) nuevo(s) extraído(s)`, {
          description: "La base de datos se actualizó automáticamente."
        });
      }
      previousLeadsCount.current = leadsArray.length;
    }
  }, [leads]);

  // Extract actual array whether it's wrapped in an object or not
  const leadsArray = useMemo(() => (Array.isArray(leads) ? leads : (leads?.leads || [])), [leads]);
  const messageCampaignOptions = useMemo(() => {
    const ids = activeCampaigns.map((campaign) => campaign.id).filter(Boolean);
    return ids.sort((a, b) => {
      const aName = campaignLabelById[a] || a;
      const bName = campaignLabelById[b] || b;
      return aName.localeCompare(bName);
    });
  }, [activeCampaigns, campaignLabelById]);
  const formatCampaignOptionLabel = (campaignId: string) => {
    const name = campaignLabelById[campaignId];
    if (!name) return 'Campaña no disponible';
    return `${name} · ${campaignId.slice(0, 8)}`;
  };

  useEffect(() => {
    if (selectedCampaignFilter && !campaignLabelById[selectedCampaignFilter]) {
      setSelectedCampaignFilter(null);
    }
  }, [selectedCampaignFilter, campaignLabelById]);

  useEffect(() => {
    if (messageScopeCampaign && !campaignLabelById[messageScopeCampaign]) {
      setMessageScopeCampaign('');
    }
  }, [messageScopeCampaign, campaignLabelById]);
  const messageScopeLeadIds = useMemo(() => {
    const allowedStatuses = new Set<string>(messageStatuses);
    return leadsArray
      .filter((lead) => {
        if (!allowedStatuses.has(String(lead.status || ''))) return false;
        if (messageScopeCampaign) return lead.campaign_id === messageScopeCampaign;
        return true;
      })
      .map((lead) => lead.id)
      .filter((id): id is number => typeof id === 'number');
  }, [leadsArray, messageStatuses, messageScopeCampaign]);
  const selectedLeads = useMemo(
    () => leadsArray.filter((lead) => typeof lead.id === 'number' && selectedLeadIds.includes(lead.id)),
    [leadsArray, selectedLeadIds],
  );
  const invalidSelectedLeads = useMemo(
    () => selectedLeads.filter((lead) => ['Follow-up 2', 'Completado', 'Respondio', 'Calificado', 'No responde', 'No interesado'].includes(lead.status)),
    [selectedLeads],
  );
  const pendingSelectedLeads = useMemo(
    () => selectedLeads.filter((lead) => lead.status === 'Pendiente'),
    [selectedLeads],
  );

  const totalLeads = leadsArray.length;
  const pendientes = leadsArray.filter((lead: Lead) => lead.status === "Pendiente").length;

  // ── Real Trust Score ──
  // Computes a 0-100 health metric based on:
  //   • Account session status & warmup (30 pts)
  //   • DM delivery success vs errors from recent jobs (40 pts)
  //   • Lead response rate (20 pts)
  //   • No recent blocks/challenges (10 pts)
  const trustScore = useMemo(() => {
    let score = 0;

    // 1. Account health (30 pts)
    if (activeAccount) {
      if (activeAccount.session_status === 'active' || !activeAccount.requires_session_warmup) score += 15;
      else if (activeAccount.warmup_status === 'running') score += 8;
      if (!activeAccount.requires_account_warmup) score += 10;
      else score += Math.min(10, ((activeAccount.account_warmup_days_completed || 0) / Math.max(1, activeAccount.account_warmup_days_total || 7)) * 10);
      if (!activeAccount.last_error) score += 5;
    } else {
      score += 5; // No account = neutral, not penalize too hard
    }

    // 2. DM delivery success (40 pts)
    const completedJobs = messageJobs.filter((j) => j.status === 'completed' || j.status === 'error');
    if (completedJobs.length > 0) {
      let totalSent = 0;
      let totalErrors = 0;
      completedJobs.forEach((j) => {
        totalSent += j.metrics?.sent || 0;
        totalErrors += j.metrics?.errors || 0;
      });
      const totalAttempted = totalSent + totalErrors;
      if (totalAttempted > 0) {
        const successRate = totalSent / totalAttempted;
        score += Math.round(successRate * 40);
      } else {
        score += 20; // No data = neutral
      }
    } else {
      score += 20; // No jobs yet = neutral
    }

    // 3. Response rate (20 pts)
    const contactedLeads = leadsArray.filter((l) => ['Primer contacto', 'Follow-up 1', 'Follow-up 2', 'Completado', 'Respondio', 'Calificado', 'No responde', 'No interesado'].includes(l.status));
    const respondedLeads = leadsArray.filter((l) => ['Respondio', 'Calificado'].includes(l.status));
    if (contactedLeads.length >= 3) {
      const responseRate = respondedLeads.length / contactedLeads.length;
      score += Math.round(responseRate * 20);
    } else {
      score += 10; // Not enough data = neutral
    }

    // 4. No blocks/challenges (10 pts)
    const reloginSignalCheck = `${activeAccount?.last_error || ''} ${activeAccount?.current_action || ''}`.toLowerCase();
    const hasBlockSignal = /challenge|block|suspicious|sospechoso|bloqueado/.test(reloginSignalCheck);
    if (!hasBlockSignal) score += 10;

    return Math.min(100, Math.max(0, Math.round(score)));
  }, [activeAccount, messageJobs, leadsArray]);
  const filteredLeads = leadsArray.filter((lead: Lead) => {
    if (crmFilter === 'all') return true;
    if (crmFilter === 'pending') return ['Pendiente', 'Listo para contactar'].includes(lead.status);
    if (crmFilter === 'contacting') return ['Primer contacto', 'Follow-up 1', 'Follow-up 2', 'Completado'].includes(lead.status);
    if (crmFilter === 'qualified') return ['Respondio', 'Calificado'].includes(lead.status);
    return lead.status === 'Error';
  });
  const sentInLast24h = useMemo(() => {
    const cutoffMs = Date.now() - (24 * 60 * 60 * 1000);
    return leadsArray.filter((lead: Lead) => {
      const lastSent = lead.sent_at || lead.contacted_at;
      if (!lastSent) return false;
      const timestamp = Date.parse(lastSent);
      if (Number.isNaN(timestamp) || timestamp < cutoffMs) return false;
      if (!activeAccount) return true;
      if (typeof lead.ig_account_id === 'number') return lead.ig_account_id === activeAccount.id;
      return true;
    }).length;
  }, [activeAccount, leadsArray]);
  const activeDailyLimit = activeAccount?.daily_dm_limit || 20;
  const activeDailySent = activeAccount ? Math.max(activeAccount.daily_dm_sent || 0, sentInLast24h) : 0;
  const activeDailyRemaining = Math.max(0, activeDailyLimit - activeDailySent);
  const selectedLeadSendEta = estimateSendEtaRangeSeconds(selectedLeadIds.length, activeAccount?.id, leadsArray);
  const warmupRange = estimateWarmupRangeSeconds(activeAccount?.account_type);
  const totalRangeForSelected = {
    min: selectedLeadSendEta.min + warmupRange.min,
    max: selectedLeadSendEta.max + warmupRange.max,
  };
  const activeOutreachJob = messageJobs.find((job) => job.kind === 'outreach' && (job.status === 'running' || job.status === 'queued'));
  const reloginSignal = `${activeAccount?.last_error || ''} ${activeAccount?.current_action || ''}`.toLowerCase();
  const accountNeedsRelogin = Boolean(
    activeAccount && /sesion no activa|sesion ausente|no hay sesion|re-loguea|login detectado|sessionid|challenge/.test(reloginSignal)
  );

  const toggleLeadSelection = (leadId: number) => {
    setSelectedLeadIds((prev) => prev.includes(leadId) ? prev.filter((id) => id !== leadId) : [...prev, leadId]);
  };

  const selectVisibleLeads = () => {
    setSelectedLeadIds(filteredLeads.map((lead) => lead.id).filter((id): id is number => typeof id === 'number'));
  };

  const clearLeadSelection = () => setSelectedLeadIds([]);

  const toggleMessageStatus = (status: 'Pendiente' | 'Listo para contactar' | 'Primer contacto' | 'Follow-up 1' | 'Follow-up 2') => {
    setMessageStatuses((prev) => {
      const exists = prev.includes(status);
      if (exists) {
        const next = prev.filter((item) => item !== status);
        return next.length > 0 ? next : prev;
      }
      return [...prev, status];
    });
  };

  const bulkLeadAction = async (action: 'delete' | 'status', status?: string, all = false) => {
    try {
      const ids = all ? [] : selectedLeadIds;
      const endpoint = action === 'delete' ? 'bulk-delete' : 'bulk-status';
      const res = await apiFetch(apiUrl(`/api/leads/${endpoint}`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids, status }),
      });
      const data = await res.json();
      if (!res.ok) {
        toast.error(data.detail || 'No pude actualizar el CRM.');
        return;
      }
      await mutateLeads();
      clearLeadSelection();
      toast.success(action === 'delete' ? 'Leads eliminados del CRM.' : `Leads marcados como ${status}.`);
    } catch {
      toast.error('Error conectando con el CRM.');
    }
  };

  const updateSingleLeadStatus = async (leadId: number, status: string, username?: string) => {
    try {
      const res = await apiFetch(apiUrl('/api/leads/bulk-status'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: [leadId], status }),
      });
      const data = await res.json();
      if (!res.ok) {
        toast.error(data.detail || 'No pude actualizar el estado.');
        return;
      }
      await mutateLeads();
      if (username) toast.success(`@${username} -> ${status}`);
    } catch {
      toast.error('Error actualizando estado del lead.');
    }
  };

  const previewMessages = async (targetIds?: number[]) => {
    if (!requireAiFeature(hasAiForMessages)) return;
    const ids = targetIds && targetIds.length > 0 ? targetIds : selectedLeadIds;
    if (ids.length === 0) {
      toast.error('Selecciona al menos un lead para generar preview.');
      return;
    }
    if (!messagePrompt.trim()) {
      toast.error('Escribe un prompt base para Message Studio.');
      return;
    }
    try {
      setIsPreparingDrafts(true);
      setDraftProgressLabel(`Analizando ${ids.length} lead(s) y generando borradores con IA...`);
      const res = await apiFetch(apiUrl('/api/messages/preview'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: currentUserId,
          ids,
          prompt: messagePrompt,
          prompt_first_contact: messagePrompt,
          prompt_follow_up_1: followUp1Prompt,
          prompt_follow_up_2: followUp2Prompt,
          master_prompt_mode: masterPromptMode,
          master_prompt: masterPromptMode === 'custom' ? masterPrompt : '',
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        toast.error(data.detail || 'No pude generar previews.');
        return;
      }
      setMessagePreviews(data.previews || []);
      await mutateLeads();
      toast.success(`Borradores preparados para ${data.count || 0} lead(s).`);
    } catch {
      toast.error('Error generando previews de mensajes.');
    } finally {
      setIsPreparingDrafts(false);
      setDraftProgressLabel('');
    }
  };

  const queueMessages = async (targetIds?: number[], campaignId?: string | null) => {
    if (!requireAiFeature(hasAiForMessages)) return;
    const ids = targetIds && targetIds.length > 0 ? targetIds : selectedLeadIds;
    if (ids.length === 0) {
      toast.error('Selecciona al menos un lead para encolar mensajes.');
      return;
    }
    if (!messagePrompt.trim()) {
      toast.error('Escribe un prompt base antes de encolar.');
      return;
    }
    try {
      setIsSavingDrafts(true);
      setDraftProgressLabel(`Guardando ${ids.length} borradores en el CRM...`);
      const res = await apiFetch(apiUrl('/api/messages/queue'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: currentUserId,
          ids,
          prompt: messagePrompt,
          prompt_first_contact: messagePrompt,
          prompt_follow_up_1: followUp1Prompt,
          prompt_follow_up_2: followUp2Prompt,
          master_prompt_mode: masterPromptMode,
          master_prompt: masterPromptMode === 'custom' ? masterPrompt : '',
          campaign_id: campaignId !== undefined ? campaignId : selectedCampaignFilter,
          follow_up_days: 3,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        toast.error(data.detail || 'No pude preparar los mensajes.');
        return;
      }
      await Promise.all([mutateLeads(), mutateMessageJobs()]);
      toast.success('Mensajes preparados. Revisa los borradores antes de enviar.');
    } catch {
      toast.error('Error preparando mensajes.');
    } finally {
      setIsSavingDrafts(false);
      setDraftProgressLabel('');
    }
  };

  const updatePendingDraftsFromMessages = async () => {
    if (messageScopeLeadIds.length === 0) {
      toast.error('No hay leads pendientes para actualizar con el alcance elegido.');
      return;
    }
    await queueMessages(messageScopeLeadIds, messageScopeCampaign || null);
  };

  const previewPendingDraftsFromMessages = async () => {
    if (messageScopeLeadIds.length === 0) {
      toast.error('No hay leads pendientes para previsualizar con el alcance elegido.');
      return;
    }
    await previewMessages(messageScopeLeadIds.slice(0, 30));
  };

  const runQueuedMessages = async () => {
    if (selectedLeadIds.length === 0) {
      toast.error('Selecciona al menos un lead antes de enviar.');
      return;
    }
    if (invalidSelectedLeads.length > 0) {
      toast.error('Hay leads seleccionados fuera de la secuencia. Quita Follow-up 2, Completado y estados cerrados.');
      return;
    }
    if (pendingSelectedLeads.length > 0) {
      toast.error('Hay leads en Pendiente. Cámbialos a Listo para contactar antes de enviar.');
      return;
    }
    if (!activeAccount) {
      toast.error('Conecta o selecciona una cuenta emisora primero.');
      return;
    }
    if (activeAccount.requires_account_warmup) {
      toast.error('Esta cuenta aun necesita varios dias de calentamiento antes de enviar mensajes.');
      return;
    }
    if (activeAccount.requires_session_warmup) {
      setPendingSendIds(selectedLeadIds);
      setShowSessionWarmupModal(true);
      return;
    }
    await executeOutreachSend(false);
  };

  const executeOutreachSend = async (overrideColdSession: boolean, targetIds?: number[]) => {
    if (!activeAccount) return;
    try {
      const res = await apiFetch(apiUrl('/api/messages/run'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: currentUserId,
          ids: targetIds || selectedLeadIds,
          dry_run: false,
          campaign_id: selectedCampaignFilter,
          account_id: activeAccount.id,
          override_cold_session: overrideColdSession,
        }),
      });
      const raw = await res.text();
      let data: { detail?: string; job?: { total?: number; eta_seconds?: number | null; eta_min_seconds?: number | null; eta_max_seconds?: number | null } } = {};
      try {
        data = raw ? JSON.parse(raw) : {};
      } catch {
        data = { detail: raw || 'Error inesperado del backend.' };
      }
      if (!res.ok) {
        toast.error(data.detail || 'No pude ejecutar la cola de outreach.');
        return;
      }
      await Promise.all([mutateMessageJobs(), mutateLeads(), mutateAccounts()]);
      const total = data.job?.total || (targetIds?.length || selectedLeadIds.length || 0);
      const estimatedRange = estimateSendEtaRangeSeconds(total);
      const etaMin = data.job?.eta_min_seconds ?? estimatedRange.min;
      const etaMax = data.job?.eta_max_seconds ?? estimatedRange.max;
      toast.success(`Envío iniciado para ${total} lead(s). ${formatDurationRange(etaMin, etaMax)}.`);
    } catch {
      toast.error('Error lanzando la cola de outreach.');
    }
  };

  const openLeadDraft = (lead: Lead) => {
    setSelectedLeadDraft(lead);
    setLeadDraftText(normalizeLeadDraftPreview(lead.last_message_preview));
  };

  const saveLeadDraft = async () => {
    if (!selectedLeadDraft?.id) return;
    try {
      const res = await apiFetch(apiUrl(`/api/leads/${selectedLeadDraft.id}/draft`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: leadDraftText }),
      });
      const data = await res.json();
      if (!res.ok) {
        toast.error(data.detail || 'No pude guardar el borrador.');
        return;
      }
      await mutateLeads();
      setSelectedLeadDraft({ ...selectedLeadDraft, last_message_preview: leadDraftText });
      toast.success('Borrador actualizado.');
    } catch {
      toast.error('Error guardando el borrador.');
    }
  };

  const regenerateLeadDraft = async () => {
    if (!selectedLeadDraft?.id) return;
    if (!requireAiFeature(hasAiForMessages)) return;
    try {
      const res = await apiFetch(apiUrl(`/api/leads/${selectedLeadDraft.id}/regenerate-draft`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: currentUserId,
          prompt_first_contact: messagePrompt,
          prompt_follow_up_1: followUp1Prompt,
          prompt_follow_up_2: followUp2Prompt,
          master_prompt_mode: masterPromptMode,
          master_prompt: masterPromptMode === 'custom' ? masterPrompt : '',
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        toast.error(data.detail || 'No pude regenerar el borrador con IA.');
        return;
      }
      setLeadDraftText(data.message || '');
      setSelectedLeadDraft({
        ...selectedLeadDraft,
        last_message_preview: data.message,
        last_message_rationale: data.rationale,
        message_variant: data.variant,
      });
      await mutateLeads();
      toast.success('Borrador regenerado con IA.');
    } catch {
      toast.error('Error regenerando el borrador.');
    }
  };

  if (currentRoute === 'auth' || currentRoute === 'register') {
    const workspaces = sortWorkspaces(workspacesData?.workspaces || [], currentUserId);
    return (
      <main className="min-h-screen bg-slate-950 flex flex-col items-center justify-center p-4">
        <div className="w-full max-w-2xl bg-slate-900/80 backdrop-blur-xl border border-slate-800 rounded-3xl p-8 shadow-2xl relative overflow-hidden animate-in fade-in zoom-in-95">
          <div className="absolute top-0 inset-x-0 h-1 bg-gradient-to-r from-purple-500 to-indigo-500"></div>

          <div className="mb-8 text-center sm:text-left">
            <img src={BRAND_LOGO_SRC} alt="Botardium" className="mx-auto mb-6 h-20 w-20 object-contain drop-shadow-[0_12px_30px_rgba(99,102,241,0.35)]" />
            <h1 className="text-2xl font-bold text-white mb-2">Tus datos viven en esta computadora</h1>
            <p className="text-slate-400 text-sm">Cada workspace local guarda su propio CRM, campañas, cuentas conectadas y sesiones. Si cambias de workspace, no se mezclan los leads.</p>
          </div>

          <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
            <div className="rounded-2xl border border-slate-800 bg-slate-950/40 p-5">
              <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Abrir workspace existente</p>
              <div className="space-y-3 overflow-y-auto max-h-[300px] pr-2" style={{ scrollbarWidth: 'thin', scrollbarColor: '#475569 #0f172a' }}>
                {workspaces.length === 0 && <p className="text-sm text-slate-500">Todavía no hay workspaces creados en esta PC.</p>}
                {workspaces.map((workspace) => (
                  <div
                    key={workspace.id}
                    className="group flex items-center justify-between rounded-2xl border border-slate-800 bg-slate-900 px-4 py-4 transition-colors hover:border-cyan-500/40 hover:bg-slate-800"
                  >
                    <button
                      type="button"
                      onClick={() => {
                        void loginToWorkspace(workspace.id, workspace.name).catch((error) => {
                          const message = error instanceof Error ? error.message : 'No pude abrir el workspace.';
                          toast.error(message);
                        });
                      }}
                      className="flex-1 text-left"
                    >
                      <p className="font-semibold text-slate-100">{workspace.name}</p>
                      <p className="mt-1 text-xs text-slate-500">Slug local: {workspace.slug}</p>
                    </button>
                    {workspaces.length > 1 && (
                      <WorkspaceDeleteButton 
                        workspaceId={workspace.id} 
                        workspaceName={workspace.name}
                        onDeleted={async () => {
                          const updated = await mutateWorkspaces();
                          const latest = updated?.workspaces || [];
                          return !latest.some((w) => w.id === workspace.id);
                        }}
                      />
                    )}
                  </div>
                ))}
              </div>
            </div>

            <form onSubmit={async (e) => {
              e.preventDefault();
              try {
                const res = await apiFetch(apiUrl('/api/workspaces'), {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ name: newWorkspaceName }),
                });
                const data = await res.json();
                if (!res.ok) {
                  toast.error(data.detail || 'No pude crear el workspace.');
                  return;
                }
                await mutateWorkspaces();
                if (data.auth?.token) {
                  applySession(data.auth as StoredSession);
                }
                setNewWorkspaceName('');
                toast.success(`Workspace ${data.name} creado en tu computadora.`);
              } catch {
                toast.error('Error creando el workspace local.');
              }
            }} className="rounded-2xl border border-slate-800 bg-slate-950/40 p-5 space-y-4">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Crear workspace nuevo</p>
              <div>
                <label className="mb-2 block text-xs font-semibold uppercase tracking-wider text-slate-500">Nombre del workspace</label>
                <input type="text" required value={newWorkspaceName} onChange={(e) => setNewWorkspaceName(e.target.value)} placeholder="Ej: Valentino / Cliente X" className="w-full bg-slate-950/50 border border-slate-800 rounded-xl px-4 py-3 text-slate-100 focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500 transition-all placeholder:text-slate-600" />
              </div>
              <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/10 px-4 py-3 text-xs leading-relaxed text-cyan-100">
                Todo lo que hagas en este workspace queda guardado localmente en esta PC: cuentas IG, leads, CRM, campañas y sesiones.
              </div>
              <button type="submit" className="w-full bg-purple-600 hover:bg-purple-500 text-white font-bold py-3 px-4 rounded-xl transition-all shadow-lg hover:shadow-xl mt-2">
                Crear workspace local
              </button>
              <button type="button" onClick={() => { void importWorkspace(); }} className="w-full rounded-xl border border-slate-700 bg-slate-900 px-4 py-3 text-sm font-medium text-slate-200 hover:border-cyan-500 hover:text-cyan-200">
                {isImportingWorkspace ? 'Importando...' : 'Importar workspace desde ZIP'}
              </button>
            </form>
          </div>
        </div>
      </main>
    );
  }

  if (currentRoute === 'accounts') {
    const hasAccounts = igAccountsData && igAccountsData.length > 0;
    const isAccountsLoading = !igAccountsData;

    return (
      <main className="min-h-screen bg-slate-950 flex flex-col items-center pt-16 p-4 text-slate-50">
        {/* Header with workspace switcher */}
        <div className="w-full max-w-5xl mb-8">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-2xl font-bold">Cuentas Vinculadas</h2>
            <div className="flex flex-wrap items-center gap-3">
              {!isAccountsLoading && (
                <>
                  <button onClick={() => setCurrentRoute('auth')} className="rounded-lg border border-slate-700 bg-slate-800 px-4 py-2 text-sm font-medium text-slate-300 hover:bg-slate-700">
                    Gestionar Workspaces
                  </button>
                  <button onClick={() => connectInstagramAccount(false)} disabled={isLoggingIn} className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-60">
                    {isLoggingIn ? 'Conectando...' : 'Conectar otra cuenta'}
                  </button>
                  {hasAccounts && (
                    <button onClick={() => setCurrentRoute('app')} className="bg-purple-600 hover:bg-purple-500 text-white font-medium px-4 py-2 rounded-lg transition-colors text-sm">
                      Ir al Dashboard Principal
                    </button>
                  )}
                </>
              )}
            </div>
          </div>

          {isAccountsLoading ? (
            // Skeleton loading
            <div className="space-y-4">
              {[1, 2].map((i) => (
                <div key={i} className="bg-slate-900 border border-slate-800 rounded-2xl p-5 animate-pulse">
                  <div className="flex items-start gap-4">
                    <div className="w-12 h-12 rounded-full bg-slate-800"></div>
                    <div className="flex-1 space-y-3">
                      <div className="h-5 bg-slate-800 rounded w-1/3"></div>
                      <div className="h-3 bg-slate-800 rounded w-1/2"></div>
                      <div className="h-2 bg-slate-800 rounded w-full"></div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : hasAccounts ? (
            <div className="grid grid-cols-1 gap-4">
              {igAccountsData.map((acc: IgAccount) => (
                <div key={acc.id} className="bg-slate-900 border border-slate-800 rounded-2xl p-5 transition-all hover:border-slate-700">
                  <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.4fr)_320px]">
                    <div className="flex min-w-0 items-start gap-4">
                      <div className="w-12 h-12 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-white font-bold text-xl shadow-lg">
                        {acc.ig_username.charAt(0).toUpperCase()}
                      </div>
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="font-semibold text-lg text-slate-100">@{acc.ig_username}</p>
                          <Badge variant="secondary" className="bg-emerald-500/10 text-emerald-400">Conexión Verificada</Badge>
                          <Badge variant="outline" className="border-slate-700 text-slate-300">
                            {acc.account_type === 'new' ? 'Cuenta nueva' : acc.account_type === 'rehab' ? 'Rehabilitación' : 'Cuenta madura'}
                          </Badge>
                          <Badge variant="outline" className={`${acc.warmup_status === 'running' ? 'border-amber-500/30 text-amber-300' : acc.requires_session_warmup ? 'border-rose-500/30 text-rose-300' : 'border-emerald-500/30 text-emerald-300'}`}>
                            {acc.warmup_status === 'running' ? 'Sesión activa' : acc.requires_session_warmup ? 'Sesión fría' : 'Sesión lista'}
                          </Badge>
                          {acc.requires_account_warmup && <Badge variant="outline" className="border-rose-500/30 text-rose-300">Calentamiento de cuenta pendiente</Badge>}
                        </div>
                        <p className="mt-3 text-sm text-slate-400">{cleanOperatorMessage(acc.current_action) || 'Aquí gestionas tu cuenta emisora: salud, límites y calentamiento de cuenta. El calentamiento previo al envío se lanza desde CRM.'}</p>
                        {acc.warmup_status === 'running' && acc.session_warmup_phase && (
                          <p className="mt-2 text-xs text-amber-300">Sesión en curso: {acc.session_warmup_phase.replaceAll('_', ' ')}</p>
                        )}
                        <div className="mt-4 w-full max-w-xl">
                          <div className="mb-1 flex items-center justify-between text-xs text-slate-500">
                            <span className="inline-flex items-center gap-2">Salud de cuenta emisora <InfoHint text="Esta pantalla gestiona solo tu cuenta emisora. El calentamiento previo al envío de mensajes se dispara desde CRM, no desde los leads." /></span>
                            <span>{acc.warmup_status === 'running' ? `${acc.warmup_progress || 0}%` : `${acc.health_score || 72}/100`}</span>
                          </div>
                          <div className="h-2 overflow-hidden rounded-full bg-slate-800">
                            <div className={`h-full rounded-full transition-all ${acc.warmup_status === 'running' ? 'bg-gradient-to-r from-amber-400 to-emerald-400' : 'bg-gradient-to-r from-cyan-400 to-indigo-400'}`} style={{ width: `${acc.warmup_status === 'running' ? acc.warmup_progress || 0 : acc.health_score || 72}%` }}></div>
                          </div>
                        </div>
                        <div className="mt-4 flex flex-wrap gap-2 text-xs">
                          <span className="rounded-full bg-slate-800 px-3 py-1 text-slate-300">DMs hoy: {acc.daily_dm_sent || 0}/{acc.daily_dm_limit || 20}</span>
                          <span className="rounded-full bg-slate-800 px-3 py-1 text-slate-300">Última sesión lista: {acc.session_warmup_last_run_at ? new Date(acc.session_warmup_last_run_at).toLocaleString() : 'Nunca'}</span>
                          <span className="rounded-full bg-slate-800 px-3 py-1 text-slate-300">Duracion: {acc.warmup_last_duration_min || 0} min</span>
                          <span className="rounded-full bg-slate-800 px-3 py-1 text-slate-300">Plan cuenta: {acc.account_warmup_days_completed || 0}/{acc.account_warmup_days_total || 0} días</span>
                        </div>
                        {acc.session_warmup_phase && acc.warmup_status !== 'running' && (() => {
                          try {
                            const logs = JSON.parse(acc.session_warmup_phase);
                            return (
                              <div className="mt-3 flex flex-wrap gap-3 text-xs bg-slate-900/50 p-3 rounded-lg border border-slate-800 items-center">
                                <span className="font-medium text-amber-400 flex items-center gap-1">
                                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
                                  Calentamiento orgánico:
                                </span>
                                <span className="text-slate-300">{logs.total_scrolls || 0} scrolls en feed</span>
                                <span className="text-slate-300">{logs.stories_viewed || 0} stories vistas</span>
                                <span className="text-slate-300">{(logs.likes_given || 0) + (logs.story_likes_given || 0)} likes dados ({logs.likes_given || 0} en posts, {logs.story_likes_given || 0} en stories)</span>
                                {logs.explore_visited && <span className="text-slate-300">Explore ✓</span>}
                              </div>
                            );
                          } catch (e) {
                            return null; // En caso de que el string sea viejo ("Fase 1..") no renderizar json
                          }
                        })()}
                        {acc.last_error && (
                          <p className="mt-3 rounded-xl border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">Ultimo error: {cleanOperatorMessage(acc.last_error)}</p>
                        )}
                      </div>
                    </div>
                    <div className="rounded-2xl border border-slate-800 bg-slate-950/50 p-4">
                      <div className="space-y-3">
                        <GlowSelect
                          value={acc.account_type || 'mature'}
                          onChange={(next) => updateAccountType(acc.id, next as 'mature' | 'new' | 'rehab')}
                          options={[
                            { value: 'mature', label: 'Cuenta madura' },
                            { value: 'new', label: 'Cuenta nueva' },
                            { value: 'rehab', label: 'Rehabilitación' },
                          ]}
                          size="md"
                          className="w-full"
                        />
                        {acc.session_status === 'verified' ? (
                          <button onClick={() => setCurrentRoute('app')} className="w-full rounded-xl bg-gradient-to-r from-cyan-500 to-emerald-500 px-4 py-2 text-sm font-semibold text-slate-950 transition-all hover:from-cyan-400 hover:to-emerald-400">
                            Usar esta cuenta
                          </button>
                        ) : (
                          <button onClick={() => reloginAccount(acc)} disabled={isReloggingAccount} className="w-full flex items-center justify-center gap-2 rounded-xl bg-rose-500 hover:bg-rose-400 px-4 py-2 text-sm font-bold text-white transition-colors disabled:opacity-50 animate-pulse-slow">
                            {isReloggingAccount ? (
                              <><span className="w-4 h-4 rounded-full border-2 border-white/30 border-t-white animate-spin" /> Conectando...</>
                            ) : (
                              <><LogIn className="w-4 h-4" /> Re-loguear Sesión (Obligatorio)</>
                            )}
                          </button>
                        )}
                        {acc.requires_account_warmup && (
                          <button onClick={() => completeAccountWarmupDay(acc.id)} className="w-full rounded-xl bg-rose-500/15 px-4 py-2 text-sm font-medium text-rose-200 hover:bg-rose-500/25">
                            Registrar día de calentamiento
                          </button>
                        )}
                        <button
                          onClick={async () => {
                            if (confirm(`¿Estás seguro que deseas desconectar la cuenta @${acc.ig_username} del sistema?`)) {
                              try {
                                const res = await apiFetch(apiUrl(`/api/accounts/${acc.id}`), { method: 'DELETE' });
                                if (res.ok) {
                                  mutateAccounts();
                                  toast.success(`Cuenta @${acc.ig_username} eliminada del pool.`);
                                }
                              } catch {
                                toast.error("Error al eliminar la cuenta.");
                              }
                            }
                          }}
                          className="w-full rounded-xl border border-rose-500/20 px-4 py-2 text-sm font-medium text-rose-300 hover:bg-rose-500/10"
                        >
                          Eliminar cuenta
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="bg-slate-900/50 border border-slate-800 border-dashed rounded-2xl p-8 text-center text-slate-500">
              Aún no has conectado ninguna cuenta de Instagram a este perfil.
            </div>
          )}
        </div>

        {!isAccountsLoading && !hasAccounts && <div className="w-full max-w-5xl bg-slate-900 border border-slate-800 rounded-3xl p-10 shadow-2xl relative animate-in fade-in slide-in-from-bottom-8">
          <div className="absolute top-0 inset-x-0 h-1 bg-gradient-to-r from-emerald-500 to-teal-500"></div>

          <div className="text-center mb-10">
            <h2 className="text-2xl font-bold tracking-tight mb-2">Conectar Cuenta de Instagram</h2>
            <p className="text-slate-400 text-sm">Inicia sesión en Instagram desde el navegador que se abrirá. El sistema detectará automáticamente tu cuenta.</p>
          </div>

          <div className="flex flex-col items-center justify-center py-8">
            <button
              onClick={() => connectInstagramAccount(true)}
              disabled={isLoggingIn}
              className="w-full max-w-sm bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-4 px-8 rounded-xl transition-all shadow-lg hover:shadow-xl flex items-center justify-center gap-3 disabled:opacity-50"
            >
              {isLoggingIn ? (
                <>
                  <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                  Esperando inicio de sesión...
                </>
              ) : (
                <>
                  <svg className="w-6 h-6" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z" />
                  </svg>
                  Iniciar Sesión en Instagram
                </>
              )}
            </button>

            <p className="text-slate-500 text-xs mt-6 max-w-sm text-center">
              Se abrirá un navegador donde podrás iniciar sesión de forma segura. No guardamos tu contraseña.
            </p>
          </div>
        </div>}
      </main>
    );
  }

  // HARD BLOCK: Si no hay cuentas verificadas, no entra a la app.
  if (currentRoute === 'app' && igAccountsData && igAccountsData.length === 0) {
    return (
      <main className="min-h-screen bg-slate-950 flex flex-col items-center justify-center p-4">
        <div className="text-center max-w-sm">
          <ShieldAlert className="w-16 h-16 text-rose-500 mx-auto mb-4 animate-pulse" />
          <h2 className="text-2xl font-bold text-white mb-2">Acceso Bloqueado</h2>
          <p className="text-slate-400 mb-8 border border-rose-500/30 bg-rose-500/10 p-4 rounded-xl text-sm">El motor requiere de una cuenta de Instagram 100% verificada para lanzar campañas de Scraping. No puedes usar el MagicBox sin un perfil emisor conectado.</p>
          <button onClick={() => setCurrentRoute('accounts')} className="bg-purple-600 hover:bg-purple-500 text-white font-bold py-3 px-8 rounded-xl w-full">
            Conectar Cuenta de IG Ahora
          </button>
        </div>
      </main>
    )
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-50 flex flex-col">
      {/* Top Navbar */}
      <header className="border-b border-slate-800 bg-slate-900/50 p-4 flex items-center justify-between sticky top-0 z-50 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <img src={BRAND_LOGO_SRC} alt="Botardium" className="h-10 w-10 object-contain drop-shadow-[0_10px_20px_rgba(99,102,241,0.28)]" />
          <h1 className="text-xl font-bold tracking-tight">Botardium</h1>
        </div>
        <div className="flex items-center gap-4">
          {currentUserEmail && (
            <div className="hidden xl:flex items-center gap-2 rounded-full border border-slate-800 bg-slate-900 px-3 py-1.5 text-xs text-slate-400">
              <span className="w-2 h-2 rounded-full bg-emerald-400"></span>
              {currentUserEmail}
            </div>
          )}
          <div className="hidden md:flex items-center gap-2">
            <Badge variant="outline" className="bg-slate-800/50 border-emerald-500/30 text-emerald-400">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse mr-1.5"></span>
              Red: Residencial (Fija)
            </Badge>
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button className="w-9 h-9 rounded-full bg-indigo-600 hover:bg-indigo-500 border border-indigo-500 flex items-center justify-center cursor-pointer transition-colors shadow-lg">
                <span className="text-sm font-semibold text-white">VR</span>
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56 bg-slate-900 border-slate-800 text-slate-200">
              <DropdownMenuLabel>Workspace Local</DropdownMenuLabel>
              <DropdownMenuSeparator className="bg-slate-800" />
              <DropdownMenuItem onClick={() => setCurrentRoute('auth')} className="focus:bg-slate-800 focus:text-white cursor-pointer">
                <SwitchCamera className="mr-2 h-4 w-4" /> Gestionar Workspaces
              </DropdownMenuItem>
              <DropdownMenuSeparator className="bg-slate-800" />
              <DropdownMenuItem onClick={() => { setCurrentRoute('accounts'); }} className="focus:bg-slate-800 focus:text-white cursor-pointer">
                <Users className="mr-2 h-4 w-4" /> Gestor de Cuentas IG
              </DropdownMenuItem>
              <DropdownMenuItem onClick={openApiKeys} className="focus:bg-slate-800 focus:text-white cursor-pointer">
                <KeyRound className="mr-2 h-4 w-4" /> API Keys
              </DropdownMenuItem>
              <DropdownMenuSeparator className="bg-slate-800" />
              <DropdownMenuItem onClick={() => {
                closeSession();
                toast.info("Workspace cerrado. Tus datos locales siguen guardados en esta PC.");
              }} className="focus:bg-slate-800 focus:text-white cursor-pointer text-rose-400">
                <LogOut className="mr-2 h-4 w-4" /> Cerrar Sesión Segura
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      {isWorkspaceSessionExpired && (
        <div className="bg-amber-500/10 border-b border-amber-500/30 p-4 flex flex-col sm:flex-row items-center justify-between gap-4 z-40 relative shadow-xl backdrop-blur-md">
          <div className="flex items-center gap-3">
            <ShieldAlert className="w-6 h-6 text-amber-500 animate-pulse" />
            <div>
              <h3 className="text-amber-400 font-bold text-sm">Tu sesión de workspace expiró</h3>
              <p className="text-slate-300 text-xs mt-0.5">Por razones de seguridad, debes re-conectar tu workspace para continuar operando sin perder tu trabajo actual.</p>
            </div>
          </div>
          <button
            onClick={() => {
              if (currentUserId !== null) {
                void loginToWorkspace(currentUserId, currentUserEmail).then(() => {
                  setIsWorkspaceSessionExpired(false);
                }).catch((error) => {
                  const message = error instanceof Error ? error.message : 'No pude re-conectar el workspace.';
                  toast.error(message);
                });
              } else {
                closeSession();
              }
            }}
            className="whitespace-nowrap bg-amber-500 hover:bg-amber-400 text-amber-950 px-5 py-2 hidden sm:flex items-center justify-center rounded-xl text-sm font-bold shadow-lg transition-colors border border-amber-400 cursor-pointer"
          >
            Re-conectar Workspace
          </button>
        </div>
      )}

      <div className="flex flex-1 min-h-0">
        {/* Sidebar */}
        <aside className="hidden w-64 shrink-0 border-r border-slate-800 bg-slate-900/30 lg:sticky lg:top-[73px] lg:flex lg:h-[calc(100vh-73px)] lg:flex-col lg:p-6">
          <div className="flex h-full flex-col justify-between gap-6 overflow-hidden">
            <div className="space-y-6 overflow-y-auto pr-1">
              <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3 px-2">Operaciones</p>
              <nav className="space-y-1">
                <button
                  onClick={() => { setCurrentView('dashboard'); }}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl font-medium transition-colors cursor-pointer text-left ${currentView === 'dashboard' ? 'bg-purple-500/10 text-purple-400' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'}`}
                >
                  <Activity className="w-4 h-4" /> Dashboard
                </button>
                <button
                  onClick={() => { setSelectedCampaignFilter(null); setCurrentView('crm'); }}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl font-medium transition-colors cursor-pointer text-left ${currentView === 'crm' ? 'bg-purple-500/10 text-purple-400' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'}`}
                >
                  <Users className="w-4 h-4" /> CRM de Leads
                </button>
                <button
                  onClick={() => { setCurrentView('campaigns'); }}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl font-medium transition-colors cursor-pointer text-left ${currentView === 'campaigns' ? 'bg-purple-500/10 text-purple-400' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'}`}
                >
                  <FolderKanban className="w-4 h-4" /> Campañas
                </button>
                <button
                  onClick={() => { setCurrentView('message_studio'); }}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl font-medium transition-colors cursor-pointer text-left ${currentView === 'message_studio' ? 'bg-purple-500/10 text-purple-400' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'}`}
                >
                  <Sparkles className="w-4 h-4" /> Message Studio
                </button>
              </nav>
            </div>

              <div className="pt-4">
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3 px-2">Seguridad</p>
              <nav className="space-y-1">
                <button
                  onClick={openHowTo}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl font-medium transition-colors cursor-pointer text-left ${currentView === 'guide' ? 'bg-purple-500/10 text-purple-400' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'}`}
                >
                  <BookOpen className="w-4 h-4" /> Cómo usarlo
                </button>
                <button
                  onClick={openApiKeys}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl font-medium transition-colors cursor-pointer text-left ${currentView === 'api_keys' ? 'bg-purple-500/10 text-purple-400' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'}`}
                >
                  <KeyRound className="w-4 h-4" /> API Keys
                </button>
                <button
                  onClick={() => toast.error("Seguridad: Todas las campañas detenidas.")}
                  className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-rose-400 font-medium hover:bg-rose-500/10 transition-colors border border-transparent hover:border-rose-500/20 group cursor-pointer text-left"
                >
                  <ShieldAlert className="w-4 h-4 group-hover:scale-110 transition-transform" /> Detener Todo
                </button>
              </nav>
              </div>
            </div>
            <div className="border-t border-slate-800 pt-4">
              <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-3 text-xs text-slate-400">
                <div className="flex items-center justify-between gap-3">
                  <span>Botardium {__APP_VERSION__}</span>
                  {updateStatus?.update_available ? <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-300">update</span> : null}
                </div>
                <div className="mt-3 space-y-2">
                  <button onClick={() => { void checkForUpdates(); }} className="flex w-full items-center justify-between rounded-xl border border-slate-800 bg-slate-900 px-3 py-2 text-left text-slate-200 hover:border-cyan-500 hover:text-cyan-200">
                    <span>{isCheckingUpdates ? 'Buscando update...' : 'Buscar actualización'}</span>
                    <Sparkles className="h-3.5 w-3.5" />
                  </button>
                  {updateStatus?.update_available ? (
                    <button onClick={() => { void openUpdateDownload(); }} className="flex w-full items-center justify-between rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-left text-emerald-200 hover:bg-emerald-500/15">
                      <span>Actualizar a {updateStatus.latest_version}</span>
                      <KeyRound className="h-3.5 w-3.5" />
                    </button>
                  ) : null}
                </div>
              </div>
            </div>
          </div>
        </aside>

        {/* Main Content Area */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-7xl p-6 md:p-10">
          {showSessionWarmupModal && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
              <div className="w-full max-w-lg rounded-3xl border border-amber-500/20 bg-slate-900 p-6 shadow-2xl">
                <p className="text-xs uppercase tracking-[0.2em] text-amber-300">Sesión fría</p>
                <h3 className="mt-3 text-2xl font-semibold text-slate-100">Conviene calentar la sesión antes de enviar</h3>
                <p className="mt-3 text-sm text-slate-300">
                  Tu cuenta está apta para outreach, pero no tiene un calentamiento corto reciente. Lo recomendado es mirar feed, stories y hacer interacciones ligeras antes de mandar mensajes.
                </p>
                <div className="mt-4 rounded-2xl border border-slate-800 bg-slate-950/60 p-4 text-sm text-slate-400">
                  Riesgo si envías frío: señales más bruscas, menor naturalidad y más probabilidad de trigger en bloques de mensajes.
                </div>
                <div className="mt-6 flex flex-wrap gap-3">
                  <button
                    onClick={async () => {
                      setShowSessionWarmupModal(false);
                      if (activeAccount) {
                        await accountWarmupAction(activeAccount.id, 'start', 10);
                      }
                      setPendingSendIds(null);
                    }}
                    className="rounded-xl bg-amber-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-amber-400"
                  >
                    Preparar cuenta ahora
                  </button>
                  <button
                    onClick={async () => {
                      setShowSessionWarmupModal(false);
                      await executeOutreachSend(true, pendingSendIds || undefined);
                      setPendingSendIds(null);
                    }}
                    className="rounded-xl bg-rose-600 px-4 py-2 text-sm font-medium text-white hover:bg-rose-500"
                  >
                    Enviar igual bajo mi riesgo
                  </button>
                  <button
                    onClick={() => { setShowSessionWarmupModal(false); setPendingSendIds(null); }}
                    className="rounded-xl bg-slate-800 px-4 py-2 text-sm font-medium text-slate-200 hover:bg-slate-700"
                  >
                    Cancelar
                  </button>
                </div>
              </div>
            </div>
          )}

          {selectedLeadDraft && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
              <div className="w-full max-w-2xl rounded-3xl border border-cyan-500/20 bg-slate-900 p-6 shadow-2xl">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-xs uppercase tracking-[0.2em] text-cyan-300">Revisión humana</p>
                    <h3 className="mt-2 text-2xl font-semibold text-slate-100">Borrador para @{selectedLeadDraft.username}</h3>
                    <p className="mt-2 text-sm text-slate-400">Revisa el mensaje antes de enviarlo. Si no te convence, vuelve a preparar borradores con otro prompt.</p>
                  </div>
                  <button onClick={() => setSelectedLeadDraft(null)} className="rounded-xl bg-slate-800 px-3 py-2 text-sm text-slate-200 hover:bg-slate-700">
                    Cerrar
                  </button>
                </div>
                <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-[0.8fr_1.2fr]">
                  <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4 text-sm text-slate-300">
                    <p className="font-medium text-slate-100">Contexto</p>
                    <p className="mt-3">Lead: @{selectedLeadDraft.username}</p>
                    {selectedLeadDraft.full_name && <p className="mt-2">Nombre: {selectedLeadDraft.full_name}</p>}
                    {selectedLeadDraft.source && <p className="mt-2">Origen: {selectedLeadDraft.source}</p>}
                    {selectedLeadDraft.status && <p className="mt-2">Estado: {selectedLeadDraft.status}</p>}
                    {selectedLeadDraft.message_variant && <p className="mt-2">Variante: {selectedLeadDraft.message_variant}</p>}
                    {selectedLeadDraft.last_message_rationale && <p className="mt-2">Rationale: {selectedLeadDraft.last_message_rationale}</p>}
                    {selectedLeadDraft.last_outreach_result && <p className="mt-2">Último resultado: {selectedLeadDraft.last_outreach_result}</p>}
                    {selectedLeadDraft.last_outreach_error && <p className="mt-2 text-rose-300">Error: {selectedLeadDraft.last_outreach_error}</p>}
                  </div>
                  <div className="rounded-2xl border border-cyan-500/20 bg-cyan-500/5 p-4 text-sm leading-relaxed text-cyan-50">
                    {selectedLeadDraft.last_message_preview || 'Todavía no hay borrador generado para este lead.'}
                  </div>
                </div>
                <div className="mt-4 rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
                  <p className="text-sm font-medium text-slate-100">Editar borrador</p>
                  <textarea
                    value={leadDraftText}
                    onChange={(e) => setLeadDraftText(e.target.value)}
                    rows={6}
                    className="mt-3 w-full rounded-xl border border-slate-800 bg-slate-950 px-4 py-3 text-sm text-slate-100 outline-none focus:border-cyan-500"
                  />
                  <div className="mt-4 flex flex-wrap gap-3">
                    <button onClick={() => { if (requireAiFeature(hasAiForMessages)) void regenerateLeadDraft(); }} title={!hasAiForMessages ? aiBlockedReason : undefined} className={`rounded-xl px-4 py-2 text-sm font-medium ${hasAiForMessages ? 'bg-emerald-600 text-white hover:bg-emerald-500' : 'bg-rose-500/15 text-rose-200 ring-1 ring-rose-500/30 hover:bg-rose-500/20'}`}>
                      Regenerar con IA
                    </button>
                    <button onClick={saveLeadDraft} className="rounded-xl bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-500">
                      Guardar borrador
                    </button>
                    <button onClick={() => setSelectedLeadDraft(null)} className="rounded-xl bg-slate-800 px-4 py-2 text-sm font-medium text-slate-200 hover:bg-slate-700">
                      Cerrar
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {(activeWarmups.length > 0 || activeCampaigns.some((campaign) => campaign.status === 'running' || campaign.status === 'warmup' || campaign.status === 'paused')) && (
            <div className="mb-6 rounded-3xl border border-cyan-500/20 bg-slate-900/80 p-5 shadow-xl">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                <div>
                  <p className="text-xs uppercase tracking-[0.2em] text-cyan-300">Motor visible</p>
                  <h3 className="mt-2 text-xl font-semibold text-slate-100">Hay procesos ejecutandose ahora mismo</h3>
                  <p className="mt-1 text-sm text-slate-400">Warmups activos: {activeWarmups.length}. Campañas activas: {activeCampaigns.filter((campaign) => campaign.status === 'running' || campaign.status === 'warmup' || campaign.status === 'paused').length}.</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button onClick={() => setCurrentRoute('accounts')} className="rounded-xl bg-amber-500/15 px-4 py-2 text-sm font-medium text-amber-200 hover:bg-amber-500/25">
                    Ver cuentas
                  </button>
                  <button onClick={() => setCurrentView('campaigns')} className="rounded-xl bg-cyan-500/15 px-4 py-2 text-sm font-medium text-cyan-200 hover:bg-cyan-500/25">
                    Ver procesos
                  </button>
                  <button onClick={() => { setSelectedCampaignFilter(null); setCurrentView('crm'); }} className="rounded-xl bg-emerald-500/15 px-4 py-2 text-sm font-medium text-emerald-200 hover:bg-emerald-500/25">
                    Ir al CRM
                  </button>
                </div>
              </div>
            </div>
          )}
          {currentView === 'dashboard' && (() => {
            const primaryRoute = lastStrategy?.sources?.[0];
            const secondaryRoutes = lastStrategy?.sources?.slice(1) || [];

            return (
              <div>
                <div className="mb-10 space-y-2 text-center sm:text-left">
                  <div className="flex items-center gap-3">
                    <h2 className="text-3xl font-bold tracking-tight text-slate-100">Búsqueda Inteligente</h2>
                    <button onClick={openHowTo} className="rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs font-medium text-slate-300 hover:border-cyan-500 hover:text-cyan-300">
                      Cómo usarlo
                    </button>
                  </div>
                  <p className="max-w-2xl text-slate-400">Dile a la IA qué perfil de clientes estás buscando hoy. El motor analizará la petición y optimizará el targeting para la campaña de Patchright automáticamante.</p>
                </div>

                <MagicBox workspaceId={currentUserId} disabled={!hasAiForMagicBox} disabledReason={aiBlockedReason} onRequireSetup={openApiKeys} onStrategyApplied={(data) => {
                  if (!Array.isArray(data?.sources) || data.sources.length === 0) {
                    toast.error('La estrategia no tiene un target valido para auto-fill.');
                    return;
                  }

                  const selectedSource = data.sources[0] || { type: 'hashtag', target: '' };
                  setLastStrategy(data);
                  setCampaignDraft({
                    name: buildCampaignDisplayName('', activeAccount?.ig_username, [selectedSource]),
                    sources: [selectedSource],
                    strategyContext: data.filter_context,
                    limit: 5,
                    executionMode: 'real',
                    minFollowers: 50,
                    minPosts: 3,
                    requireCoherence: true,
                  });
                  toast.success(`Ruta aplicada con ${data.sources.length} source(s)`, {
                    description: 'Complete la configuracion y lance la campana desde el panel operativo.',
                  });
                }} />

                <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-[1.2fr_0.8fr]">
                  <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-xl">
                    <div className="mb-5 flex items-start justify-between gap-4">
                      <div>
                        <h3 className="text-lg font-semibold text-slate-100">Panel Operativo</h3>
                        <p className="mt-1 text-sm text-slate-400">Una campaña = un source. La IA te sugiere alternativas, pero scrapeas de a una para entender mejor el rendimiento.</p>
                      </div>
                      <Badge variant="secondary" className="bg-slate-800 text-slate-300">1 source por campaña</Badge>
                    </div>

                    <div className="grid grid-cols-1 gap-4 md:grid-cols-[1.2fr_0.8fr_0.8fr]">
                      <div className="space-y-2 md:col-span-3">
                        <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Nombre de campaña</label>
                        <input type="text" value={campaignDraft.name} onChange={(e) => setCampaignDraft((prev) => ({ ...prev, name: e.target.value.slice(0, 80) }))} placeholder="Ej: Constructoras CABA" className="w-full rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-slate-200 outline-none focus:border-purple-500" />
                      </div>
                      <div className="space-y-2 md:col-span-2">
                        <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Cuenta Emisora</label>
                        <div className="rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-slate-200">{activeAccount ? `@${activeAccount.ig_username}` : 'Sin cuenta conectada'}</div>
                      </div>
                      <div className="space-y-2">
                        <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Limite Inicial</label>
                        <input type="number" min={5} max={50} value={campaignDraft.limit} onChange={(e) => {
                          const next = Number(e.target.value);
                          const normalized = Number.isFinite(next) ? Math.max(5, Math.min(50, next)) : 5;
                          setCampaignDraft((prev) => ({ ...prev, limit: normalized }));
                        }} className="w-full rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-slate-200 outline-none focus:border-purple-500" />
                      </div>
                      <div className="space-y-2">
                        <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Modo de Ejecucion</label>
                        <GlowSelect value={campaignDraft.executionMode} onChange={(next) => setCampaignDraft((prev) => ({ ...prev, executionMode: next as CampaignDraft['executionMode'] }))} options={[{ value: 'real', label: 'Real' }, { value: 'test', label: 'Test' }]} size="md" />
                      </div>
                    </div>

                    <p className="mt-3 text-xs text-slate-500">Real usa tu sesion autenticada y el extractor verdadero para hashtag y followers. Test solo simula el pipeline sin tocar Instagram ni el CRM.</p>

                    <div className="mt-4 rounded-2xl border border-slate-800 bg-slate-950/40 p-4">
                      <div className="mb-4">
                        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Filtros de Calidad</p>
                        <p className="mt-1 text-sm text-slate-400">Ajusta volumen con min followers y min posts. El anti-ruido está pensado para limpiar cuentas fuera de rubro.</p>
                      </div>
                      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                        <div className="space-y-2">
                          <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Min Followers</label>
                          <input type="number" min={0} value={campaignDraft.minFollowers} onChange={(e) => setCampaignDraft((prev) => ({ ...prev, minFollowers: Number(e.target.value) || 0 }))} className="w-full rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-slate-200 outline-none focus:border-purple-500" />
                        </div>
                        <div className="space-y-2">
                          <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Min Posts</label>
                          <input type="number" min={0} value={campaignDraft.minPosts} onChange={(e) => setCampaignDraft((prev) => ({ ...prev, minPosts: Number(e.target.value) || 0 }))} className="w-full rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-slate-200 outline-none focus:border-purple-500" />
                        </div>
                        <div className={`rounded-2xl border px-4 py-3 transition-colors md:col-span-2 ${campaignDraft.requireCoherence ? 'border-emerald-500/40 bg-emerald-500/10' : 'border-slate-800 bg-slate-950/60'}`}>
                          <div className="flex items-center justify-between gap-4">
                            <div>
                              <p className="text-sm font-semibold text-slate-100">Anti-ruido de nicho</p>
                              <p className="mt-0.5 text-xs text-slate-400">Activado por defecto. Filtra cuentas claramente fuera de rubro.</p>
                            </div>
                            <button type="button" role="switch" aria-checked={campaignDraft.requireCoherence} onClick={() => setCampaignDraft((prev) => ({ ...prev, requireCoherence: !prev.requireCoherence }))} className={`relative inline-flex h-9 w-16 shrink-0 items-center rounded-full border transition-colors ${campaignDraft.requireCoherence ? 'border-emerald-400/70 bg-emerald-500/30' : 'border-slate-700 bg-slate-800'}`}>
                              <span className={`inline-block h-7 w-7 rounded-full bg-white shadow transition-transform ${campaignDraft.requireCoherence ? 'translate-x-8' : 'translate-x-1'}`} />
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>

                    <div className="mt-4 space-y-3">
                      <div className="flex items-center justify-between gap-3">
                        <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Source de targeting</label>
                        <span className="rounded-full border border-cyan-500/20 bg-cyan-500/10 px-3 py-1 text-xs font-medium text-cyan-200">1 source por campaña</span>
                      </div>
                      <details className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                        <summary className="cursor-pointer text-sm font-medium text-slate-200">Tips para hashtags (evitar nicho vacio)</summary>
                        <div className="mt-2 space-y-1 text-xs text-slate-400">
                          <p>1) Probá singular y plural: `esteticaargentina` / `esteticasargentina`.</p>
                          <p>2) Si no aparece volumen, usá variante cercana mas amplia y mantené geografía.</p>
                          <p>3) Si Botardium marca “Hashtag no encontrado” o “muy reducido”, cambiá el source antes de relanzar.</p>
                        </div>
                      </details>
                      {campaignDraft.sources[0] && (
                        <div className="grid grid-cols-1 gap-3 rounded-xl border border-slate-800 bg-slate-950/60 p-3 md:grid-cols-[180px_1fr]">
                          <GlowSelect value={campaignDraft.sources[0].type} onChange={(next) => setSourceAt(0, 'type', next)} options={[{ value: 'hashtag', label: 'Hashtag' }, { value: 'followers', label: 'Followers' }, { value: 'location', label: 'Location' }]} size="md" />
                          <div className="flex items-center rounded-xl border border-slate-800 bg-slate-900 px-4 py-3">
                            <span className="mr-2 text-slate-500">{campaignDraft.sources[0].type === 'hashtag' ? '#' : campaignDraft.sources[0].type === 'followers' ? '@' : ''}</span>
                            <input type="text" value={campaignDraft.sources[0].target} onChange={(e) => setSourceAt(0, 'target', e.target.value)} placeholder={campaignDraft.sources[0].type === 'hashtag' ? 'Ej: brokersinmobiliarios' : campaignDraft.sources[0].type === 'followers' ? 'Ej: constructora' : 'Ej: miamicondos'} className="w-full bg-transparent text-slate-100 outline-none placeholder:text-slate-600" />
                          </div>
                        </div>
                      )}
                    </div>

                    <div className="mt-5 flex flex-wrap gap-3">
                      <button onClick={async () => {
                        if (!activeAccount) {
                          toast.error('Necesitas una cuenta de Instagram conectada para lanzar la campana.');
                          return;
                        }
                        if (activeAccount.session_status !== 'verified') {
                          toast.error('La cuenta seleccionada no tiene una sesión activa válida. Re-conéctala desde Cuentas o verifícala antes de lanzar una campaña.');
                          return;
                        }
                        const cleanedSources = campaignDraft.sources.map((source) => ({ ...source, target: source.target.trim() })).filter((source) => source.target);
                        if (!cleanedSources.length) {
                          toast.error('Agrega al menos un source valido para lanzar la campana.');
                          return;
                        }
                        try {
                          const res = await apiFetch(apiUrl('/api/bot/start'), {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                              workspace_id: currentUserId,
                              username: activeAccount.ig_username,
                              campaign_name: campaignDraft.name.trim(),
                              strategy_context: campaignDraft.strategyContext,
                              sources: cleanedSources.map((source) => ({ type: source.type, value: source.target })),
                              limit: Math.max(5, campaignDraft.limit),
                              warmup_mode: 'skip',
                              warmup_minutes: 0,
                              execution_mode: campaignDraft.executionMode,
                              filter_profile: 'strict',
                              min_followers: campaignDraft.minFollowers,
                              min_posts: campaignDraft.minPosts,
                              require_identity: true,
                              require_keyword_match: false,
                              require_coherence: campaignDraft.requireCoherence,
                            }),
                          });
                          const data = await res.json().catch(() => ({}));
                          if (!res.ok) {
                            toast.error(data.detail || 'No pude lanzar la campana.');
                            if (res.status === 409) {
                              await mutateAccounts();
                              setCurrentView('admin_accounts');
                            }
                            return;
                          }
                          await mutateBotStatus();
                          toast.success(`Campana preparada con ${cleanedSources.length} source(s)`, { description: `Cuenta emisora: @${activeAccount.ig_username}.` });
                          setCurrentView('campaigns');
                        } catch {
                          toast.error('Error conectando con el motor de ejecucion.');
                        }
                      }} className="rounded-xl bg-purple-600 px-5 py-3 font-semibold text-white transition-colors hover:bg-purple-500">
                        Lanzar Campana
                      </button>
                      <button onClick={() => {
                        setCampaignDraft({ name: '', sources: [{ type: 'followers', target: '' }], strategyContext: undefined, limit: 5, executionMode: 'real', minFollowers: 50, minPosts: 3, requireCoherence: true });
                        setLastStrategy(null);
                        toast.info('Borrador operativo limpiado.');
                      }} className="rounded-xl bg-slate-800 px-5 py-3 font-semibold text-slate-200 transition-colors hover:bg-slate-700">
                        Limpiar Borrador
                      </button>
                    </div>
                  </div>

                  <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-xl">
                    <h3 className="text-lg font-semibold text-slate-100">Ultima Ruta IA</h3>
                    {!lastStrategy ? (
                      <p className="mt-4 text-sm text-slate-500">Todavia no aplicaste una ruta. Usa Auto-Rellenar para poblar el panel operativo.</p>
                    ) : (
                      <div className="mt-4 space-y-4">
                        <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
                          <p className="mb-2 text-xs uppercase tracking-wider text-slate-500">Hashtag principal</p>
                          {primaryRoute ? (
                            <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/10 p-3">
                              <div className="flex items-center justify-between gap-3">
                                <div>
                                  <p className="text-sm font-semibold text-slate-100">#{primaryRoute.target}</p>
                                  <p className="mt-1 text-xs text-slate-400">La campaña va a scrapear este hashtag completo antes de pasar a otro.</p>
                                </div>
                                <button onClick={() => setCampaignDraft((prev) => ({ ...prev, sources: [primaryRoute] }))} className="rounded-lg bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-cyan-500">
                                  Usar este
                                </button>
                              </div>
                            </div>
                          ) : null}
                          {secondaryRoutes.length > 0 ? (
                            <div className="mt-4">
                              <p className="mb-2 text-xs uppercase tracking-wider text-slate-500">Siguientes recomendados</p>
                              <div className="space-y-2">
                                {secondaryRoutes.map((source, index) => (
                                  <div key={`${source.type}-${source.target}-${index}`} className="flex items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2">
                                    <span className="text-sm text-slate-300">#{source.target}</span>
                                    <button onClick={() => setCampaignDraft((prev) => ({ ...prev, name: buildCampaignDisplayName('', activeAccount?.ig_username, [source]), sources: [source] }))} className="rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700">
                                      Probar este
                                    </button>
                                  </div>
                                ))}
                              </div>
                            </div>
                          ) : null}
                        </div>
                        <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
                          <p className="mb-2 text-xs uppercase tracking-wider text-slate-500">Razonamiento</p>
                          <p className="text-sm leading-relaxed text-slate-300">{lastStrategy.reasoning}</p>
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                <div className="mt-12 grid grid-cols-1 gap-6 md:grid-cols-3">
                  <div className="group relative overflow-hidden rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-xl transition-colors hover:border-purple-500/30">
                    <div className="absolute right-0 top-0 p-4 opacity-10 transition-opacity group-hover:opacity-20"><Users className="h-16 w-16 text-purple-400" /></div>
                    <p className="mb-1 text-sm font-medium text-slate-400">Leads Totales</p>
                    <p className="text-4xl font-bold text-slate-100">{totalLeads}</p>
                    <div className="mt-4 w-fit rounded-full bg-purple-500/10 px-2 py-1 text-xs font-medium text-purple-400">Sincronizado via SQLite</div>
                  </div>
                  <div className="group relative overflow-hidden rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-xl transition-colors hover:border-amber-500/30">
                    <div className="absolute right-0 top-0 p-4 opacity-10 transition-opacity group-hover:opacity-20"><Activity className="h-16 w-16 text-amber-400" /></div>
                    <p className="mb-1 text-sm font-medium text-slate-400">En Cola (Pendientes)</p>
                    <p className="text-4xl font-bold text-slate-100">{pendientes}</p>
                    <div className="mt-4 w-fit rounded-full bg-amber-500/10 px-2 py-1 text-xs font-medium text-amber-400">Esperando Outreach</div>
                  </div>
                  <div className={`group relative overflow-hidden rounded-2xl border bg-slate-900 p-6 shadow-xl ${trustScore >= 70 ? 'border-emerald-500/30' : trustScore >= 40 ? 'border-amber-500/30' : 'border-rose-500/30'}`}>
                    <div className="absolute right-0 top-0 p-4 opacity-10 transition-opacity group-hover:opacity-20"><BadgeCheck className={`h-16 w-16 ${trustScore >= 70 ? 'text-emerald-400' : trustScore >= 40 ? 'text-amber-400' : 'text-rose-400'}`} /></div>
                    <div className="flex items-start justify-between">
                      <div>
                        <p className="mb-1 text-sm font-medium text-slate-400">Trust Score</p>
                        <p className={`text-4xl font-bold ${trustScore >= 70 ? 'text-emerald-400' : trustScore >= 40 ? 'text-amber-400' : 'text-rose-400'}`}>{trustScore}%</p>
                      </div>
                      <Badge className={`border-none ${trustScore >= 70 ? 'bg-emerald-500/10 text-emerald-400' : trustScore >= 40 ? 'bg-amber-500/10 text-amber-400' : 'bg-rose-500/10 text-rose-400'}`}>{trustScore >= 70 ? 'Seguro' : trustScore >= 40 ? 'Moderado' : 'Riesgo'}</Badge>
                    </div>
                    <div className="mt-4 h-1.5 w-full rounded-full bg-slate-800"><div className={`h-1.5 rounded-full transition-all ${trustScore >= 70 ? 'bg-emerald-500' : trustScore >= 40 ? 'bg-amber-500' : 'bg-rose-500'}`} style={{ width: `${trustScore}%` }} /></div>
                    <p className="mt-3 text-[10px] text-slate-600">Sesión · Entregas · Respuestas · Seguridad</p>
                  </div>
                </div>

                <div className="mt-8 overflow-hidden rounded-2xl border border-slate-800 bg-slate-900 shadow-xl">
                  <div className="flex items-center justify-between border-b border-slate-800 bg-slate-800/30 p-3">
                    <h3 className="font-semibold text-slate-200">Actividad de Scraping (Live)</h3>
                    <Badge variant="secondary" className="bg-purple-500/20 text-purple-300">Polling Activo • 2s</Badge>
                  </div>
                  <div className="overflow-x-auto p-0">
                    <table className="w-full text-left text-sm">
                      <thead className="border-b border-slate-800 bg-slate-900 text-xs uppercase text-slate-400">
                        <tr>
                          <th className="px-6 py-3">Usuario IG</th>
                          <th className="px-6 py-3">Estado</th>
                          <th className="px-6 py-3">Origen</th>
                        </tr>
                      </thead>
                      <tbody>
                        {leadsArray.length > 0 ? leadsArray.slice(0, 5).map((lead: Lead, i: number) => (
                          <tr key={i} className="border-b border-slate-800/50 bg-slate-900 transition-colors hover:bg-slate-800/50">
                            <td className="px-6 py-4">
                              <div className="font-medium text-slate-200">@{lead.username}</div>
                              {lead.full_name && <div className="text-xs text-slate-500">{lead.full_name}</div>}
                              {lead.last_message_preview && <div className="mt-2 max-w-sm rounded-lg border border-cyan-500/20 bg-cyan-500/5 px-2 py-1 text-xs text-cyan-100">{lead.last_message_preview.length > 140 ? `${lead.last_message_preview.slice(0, 140)}...` : lead.last_message_preview}</div>}
                              {lead.last_message_rationale && <div className="mt-2 text-xs text-slate-500">{lead.last_message_rationale}</div>}
                            </td>
                            <td className="px-6 py-4">
                              <Badge variant="outline" className={getLeadStatusTone(lead.status)}>{lead.status}</Badge>
                              {lead.last_outreach_result && <div className="mt-2 text-xs text-slate-500">Resultado: {lead.last_outreach_result}</div>}
                              {lead.last_outreach_error && <div className="mt-2 max-w-xs text-xs text-rose-300">{lead.last_outreach_error}</div>}
                            </td>
                            <td className="px-6 py-4 text-slate-400"><span className="rounded-full border border-slate-700 bg-slate-950/60 px-3 py-1 text-xs text-slate-300">{formatSourceLabel(lead.source)}</span></td>
                          </tr>
                        )) : (
                          <tr>
                            <td colSpan={3} className="px-6 py-8 text-center text-slate-500">Cargando data del CRM o sin resultados...</td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            );
          })()}

          {currentView === 'crm' && (
            <div className="animate-in fade-in slide-in-from-bottom-4">
              <div className="mb-8">
                <div className="flex items-center gap-3">
                  <h2 className="text-3xl font-bold tracking-tight text-slate-100">CRM de Leads</h2>
                  <button onClick={openHowTo} className="rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs font-medium text-slate-300 hover:border-cyan-500 hover:text-cyan-300">
                    Cómo usarlo
                  </button>
                </div>
                <p className="text-slate-400">Total visibles: {filteredLeads.length}. Administra estados, seguimiento y la futura cola de mensajería.</p>
              </div>

              <div className="mb-4 rounded-2xl border border-slate-800 bg-slate-900 p-4 shadow-xl">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="rounded-full bg-slate-800 px-3 py-1 text-slate-300">Campaña: {selectedCampaignFilter ? (campaignLabelById[selectedCampaignFilter] || 'sin campaña') : 'todas'}</span>
                  <span className="rounded-full bg-slate-800 px-3 py-1 text-slate-300">Seleccionados: {selectedLeadIds.length}</span>
                  <span className="rounded-full bg-slate-800 px-3 py-1 text-slate-300">Pendientes: {filteredLeads.filter((lead) => ['Pendiente', 'Listo para contactar'].includes(lead.status)).length}</span>
                  {activeAccount && <span className="inline-flex items-center gap-2 rounded-full bg-slate-800 px-3 py-1 text-slate-300">Límite diario: {activeDailySent}/{activeDailyLimit} <InfoHint text="El límite diario corta el envío para evitar patrones cíclicos. Botardium deja el resto para la próxima ventana segura." /></span>}
                  {activeAccount && <span className={`rounded-full px-3 py-1 ${activeAccount.requires_session_warmup ? 'bg-amber-500/10 text-amber-300' : 'bg-emerald-500/10 text-emerald-300'}`}>Cuenta emisora {activeAccount.requires_session_warmup ? 'a preparar' : 'lista'}</span>}
                </div>
                {invalidSelectedLeads.length > 0 && (
                  <div className="mt-3 rounded-xl border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                    Hay {invalidSelectedLeads.length} lead(s) seleccionados fuera de secuencia. Quita estados cerrados (`Follow-up 2`, `Completado`, `Respondio`, `No interesado`) antes de enviar.
                  </div>
                )}
                {pendingSelectedLeads.length > 0 && (
                  <div className="mt-3 rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                    Para enviar mensajes, los leads no pueden estar en Pendiente. Pásalos a `Listo para contactar` primero.
                  </div>
                )}
              </div>

              <div className="mb-6 grid grid-cols-1 gap-4 xl:grid-cols-[0.95fr_1.05fr]">
                <div className="rounded-2xl border border-slate-800 bg-slate-900 p-4 shadow-xl">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-xs uppercase tracking-wider text-slate-500">Message Studio</p>
                      <p className="mt-1 text-sm font-semibold text-slate-100">Prompts y borradores</p>
                      <p className="mt-1 text-xs text-slate-400">Actualiza mensajes en bloque y revisa variantes antes de enviar.</p>
                    </div>
                    <button onClick={() => setCurrentView('message_studio')} className="rounded-lg bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-cyan-500">
                      Abrir
                    </button>
                  </div>
                </div>

                <div className="rounded-2xl border border-slate-800 bg-slate-900 p-4 shadow-xl">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-xs uppercase tracking-wider text-slate-500">Monitor de estado</p>
                      <p className="mt-1 text-sm font-semibold text-slate-100">Próximo paso operativo</p>
                      <p className="mt-1 text-sm text-slate-300">
                        {activeOutreachJob
                          ? `Envío en curso: ${activeOutreachJob.processed}/${activeOutreachJob.total} leads${activeOutreachJob.current_lead ? ` · @${activeOutreachJob.current_lead}` : ''}.`
                          : activeAccount?.warmup_status === 'running'
                            ? `Calentamiento en curso para ${selectedLeadIds.length > 0 ? `${selectedLeadIds.length} lead(s) seleccionados` : 'la cuenta'}: ${activeAccount.current_action || 'trabajando...'}`
                            : activeAccount?.requires_session_warmup
                              ? 'Antes del próximo envío: calienta la sesión 15-25 min si la cuenta no es personal madura.'
                              : selectedLeadIds.length > 0
                                ? `Sesión lista. Puedes enviar ${selectedLeadIds.length} lead(s) seleccionados.`
                                : 'La cuenta está lista para el próximo envío dentro de la ventana segura.'}
                      </p>
                    </div>
                    <span className="text-sm text-slate-400">
                      {activeOutreachJob
                        ? `${formatDurationRange(activeOutreachJob.eta_min_seconds, activeOutreachJob.eta_max_seconds)} · ${activeOutreachJob.processed}/${activeOutreachJob.total}`
                        : activeAccount?.warmup_status === 'running'
                          ? `Progreso warmup: ${activeAccount.warmup_progress || 0}%`
                          : selectedLeadIds.length > 0
                            ? `${formatDurationRange(selectedLeadSendEta.min, selectedLeadSendEta.max)} · lote ${selectedLeadIds.length}`
                            : `Cupo restante hoy: ${activeDailyRemaining} DM(s)`}
                    </span>
                  </div>
                </div>
              </div>

              {messageJobs.length > 0 && (
                <div className="mb-6 rounded-2xl border border-slate-800 bg-slate-900 p-5 shadow-xl">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-xs uppercase tracking-wider text-slate-500">Cola visible</p>
                      <h3 className="mt-1 text-lg font-semibold text-slate-100">Envíos recientes</h3>
                    </div>
                    <Badge variant="outline" className="border-emerald-500/30 text-emerald-300">{messageJobs.length} envío(s)</Badge>
                  </div>
                  <div className="mt-4 grid grid-cols-1 xl:grid-cols-2 gap-4">
                    {messageJobs.slice(0, 4).map((job) => (
                      <div key={job.id} className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
                        <div className="flex items-center justify-between gap-3">
                          <p className="text-sm font-medium text-slate-100">Envío {job.id.slice(0, 8)}</p>
                          <div className="flex items-center gap-2">
                            <Badge variant="outline" className="border-slate-700 text-slate-300">
                              DM
                            </Badge>
                            <Badge
                              variant="outline"
                              className={
                                job.status === 'completed' ? 'border-emerald-500/30 text-emerald-300' : job.status === 'error' ? 'border-rose-500/30 text-rose-300' : 'border-cyan-500/30 text-cyan-300'}>{formatJobStatusLabel(job.status)}</Badge>
                          </div>
                        </div>
                        <p className="mt-2 text-xs text-slate-400">{cleanOperatorMessage(job.current_action)}</p>
                        <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-800">
                          <div className="h-full rounded-full bg-gradient-to-r from-cyan-400 to-emerald-400" style={{ width: `${job.progress}%` }}></div>
                        </div>
                        <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
                          <span>{job.processed}/{job.total} procesados</span>
                          {job.current_lead && <span>lead actual: @{job.current_lead}</span>}
                          <span>{formatDurationRange(job.eta_min_seconds, job.eta_max_seconds)}</span>
                          <span>campaña: {job.campaign_id ? (campaignLabelById[job.campaign_id] || job.campaign_id.slice(0, 8)) : 'global'}</span>
                          {typeof job.metrics?.sent === 'number' && <span>enviados: {job.metrics.sent}</span>}
                          {typeof job.metrics?.errors === 'number' && <span>errores: {job.metrics.errors}</span>}
                          {typeof job.metrics?.no_dm_button === 'number' && job.metrics.no_dm_button > 0 && <span>sin botón DM: {job.metrics.no_dm_button}</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {activeAccount && accountNeedsRelogin && (
                <div className="mb-6 rounded-2xl border border-rose-500/20 bg-rose-500/10 p-4 shadow-xl">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-sm text-rose-200">La sesión parece inválida o vencida. Re-loguea la cuenta para que el warmup no se corte al instante.</p>
                    <button
                      onClick={reloginActiveAccount}
                      disabled={isReloggingAccount}
                      className="rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-500 disabled:opacity-50"
                    >
                      {isReloggingAccount ? 'Re-logueando...' : 'Re-loguear cuenta'}
                    </button>
                  </div>
                </div>
              )}

              <div className="bg-slate-900 border border-slate-800 rounded-2xl shadow-xl">
                <div className="p-4 border-b border-slate-800 bg-slate-800/30 flex justify-between items-center">
                  <div>
                    <h3 className="font-semibold text-slate-200">Base de Datos Completa</h3>
                    <p className="text-xs text-slate-500 mt-1">Selecciona, filtra y limpia leads desde aca.</p>
                  </div>
                  <Badge variant="secondary" className="bg-emerald-500/20 text-emerald-400">
                    Live Sync Activo
                  </Badge>
                </div>
                <div className="flex flex-col gap-2 border-b border-slate-800 bg-slate-900/70 p-3 xl:flex-row xl:items-center xl:justify-between">
                  <div className="flex flex-wrap items-center gap-2">
                    <GlowSelect
                      value={crmFilter}
                      onChange={(next) => setCrmFilter(next as typeof crmFilter)}
                      options={[
                        { value: 'all', label: 'Todos los leads' },
                        { value: 'pending', label: 'Pendientes' },
                        { value: 'contacting', label: 'En contacto' },
                        { value: 'qualified', label: 'Respondieron' },
                        { value: 'error', label: 'Error' },
                      ]}
                      className="min-w-[170px]"
                    />
                    <button onClick={selectVisibleLeads} className="rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700">Seleccionar visibles</button>
                    <button onClick={clearLeadSelection} className="rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700">Limpiar selección</button>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <button onClick={warmupActiveSessionFromCrm} className="rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-100 hover:bg-slate-700">
                      Preparar cuenta emisora
                    </button>
                    <InfoHint text="Preparar cuenta emisora hace un warmup corto de sesión antes de enviar. No calienta leads." />
                    <button onClick={() => setCurrentView('message_studio')} className="rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-100 hover:bg-slate-700">
                      Gestionar mensajes
                    </button>
                    <button onClick={runQueuedMessages} disabled={selectedLeadIds.length === 0 || invalidSelectedLeads.length > 0 || pendingSelectedLeads.length > 0} className="rounded-lg bg-white px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-slate-200 disabled:opacity-40">
                      Enviar seleccionados
                    </button>
                    <InfoHint text="Envío masivo solo para estados activos. Pendiente y estados cerrados se bloquean para evitar errores." />
                    <GlowSelect
                      value={bulkStatusSelection}
                      onChange={setBulkStatusSelection}
                      options={CRM_STATUS_OPTIONS.map((status) => ({ value: status, label: status }))}
                      className="min-w-[170px]"
                    />
                    <button onClick={() => bulkLeadAction('status', bulkStatusSelection)} disabled={selectedLeadIds.length === 0} className="rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-100 hover:bg-slate-700 disabled:opacity-40">Aplicar estado</button>
                    <button onClick={() => bulkLeadAction('delete')} disabled={selectedLeadIds.length === 0} className="rounded-lg bg-rose-500/10 px-3 py-1.5 text-xs font-medium text-rose-300 hover:bg-rose-500/20 disabled:opacity-40">Eliminar seleccionados</button>
                    <button onClick={() => bulkLeadAction('delete', undefined, true)} className="rounded-lg bg-rose-500/10 px-3 py-1.5 text-xs font-medium text-rose-300 hover:bg-rose-500/20">Vaciar CRM</button>
                  </div>
                </div>
                <div className="min-h-[400px] overflow-visible p-0">
                  <table className="w-full text-left text-sm" style={{ tableLayout: 'fixed' }}>
                    <colgroup>
                      <col style={{ width: '3%' }} />
                      <col style={{ width: '18%' }} />
                      <col style={{ width: '20%' }} />
                      <col style={{ width: '15%' }} />
                      <col style={{ width: '12%' }} />
                      <col style={{ width: '7%' }} />
                      <col style={{ width: '9%' }} />
                      <col style={{ width: '7%' }} />
                      <col style={{ width: '9%' }} />
                    </colgroup>
                    <thead className="border-b border-slate-800 bg-slate-900 text-xs uppercase text-slate-400">
                      <tr>
                        <th className="w-12 bg-slate-900 px-3 py-2">
                          <GlowCheckbox
                            checked={filteredLeads.length > 0 && selectedLeadIds.length === filteredLeads.map((lead) => lead.id).filter((id): id is number => typeof id === 'number').length}
                            onChange={(next) => next ? selectVisibleLeads() : clearLeadSelection()}
                            ariaLabel="Seleccionar todos los leads visibles"
                          />
                        </th>
                        <th className="bg-slate-900 px-3 py-2">Usuario IG</th>
                        <th className="bg-slate-900 px-3 py-2">Mensaje</th>
                        <th className="bg-slate-900 px-3 py-2">Estado</th>
                        <th className="bg-slate-900 px-3 py-2">Origen</th>
                        <th className="bg-slate-900 px-3 py-2">Campaña</th>
                        <th className="bg-slate-900 px-3 py-2">Detectado</th>
                        <th className="bg-slate-900 px-3 py-2 text-right">Enviar</th>
                        <th className="bg-slate-900 px-3 py-2 text-right">Acciones</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredLeads.length > 0 ? filteredLeads.map((lead: Lead, i: number) => (
                        <tr key={i} className="bg-slate-900 border-b border-slate-800/50 hover:bg-slate-800/50 transition-colors">
                          <td className="px-3 py-2 align-middle">
                            {typeof lead.id === 'number' && (
                              <GlowCheckbox
                                checked={selectedLeadIds.includes(lead.id)}
                                onChange={() => toggleLeadSelection(lead.id!)}
                                ariaLabel={`Seleccionar lead @${lead.username}`}
                              />
                            )}
                          </td>
                          <td className="px-3 py-2 align-middle">
                            <HoverText text={`@${lead.username}`}>
                              <div className="truncate font-medium leading-tight text-slate-200">@{lead.username}</div>
                            </HoverText>
                            {lead.full_name && (
                              <HoverBlock text={lead.full_name} className="mt-0.5">
                                <div className="line-clamp-2 text-xs leading-tight text-slate-500">{lead.full_name}</div>
                              </HoverBlock>
                            )}
                          </td>
                          <td className="px-3 py-2 align-middle">
                            {(() => {
                              const preview = normalizeLeadDraftPreview(lead.last_message_preview);
                              return (
                                <div className="max-w-[260px]">
                                  <HoverBlock text={preview || 'Sin borrador'}>
                                    <div
                                      className="rounded-md border border-cyan-500/20 bg-cyan-500/5 px-3 py-2 text-[11px] leading-4 text-cyan-100"
                                      style={{ minHeight: 42 }}
                                    >
                                      <span
                                        className="block overflow-hidden"
                                        style={{
                                          display: '-webkit-box',
                                          WebkitLineClamp: 2,
                                          WebkitBoxOrient: 'vertical',
                                        }}
                                      >
                                        {preview || 'Sin borrador'}
                                      </span>
                                    </div>
                                  </HoverBlock>
                                  <button
                                    onClick={() => openLeadDraft(lead)}
                                    className="mt-1 inline-flex items-center whitespace-nowrap text-[11px] font-semibold text-cyan-400 transition-colors hover:text-cyan-300"
                                  >
                                    Ver borrador
                                  </button>
                                </div>
                              );
                            })()}
                          </td>
                          <td className="px-3 py-2 align-middle">
                            {typeof lead.id === 'number' && (
                              <GlowSelect
                                value={lead.status}
                                onChange={async (next) => {
                                  if (typeof lead.id === 'number') {
                                    await updateSingleLeadStatus(lead.id, next, lead.username);
                                  }
                                }}
                                options={CRM_STATUS_OPTIONS.map((status) => ({ value: status, label: status }))}
                                className="w-full min-w-0"
                              />
                            )}
                          </td>
                          <td className="px-3 py-2 align-middle text-slate-400">
                            <div className="inline-block max-w-full rounded-full border border-slate-700 bg-slate-950/60 px-3 py-1 text-xs text-slate-300">
                              <HoverText text={formatSourceLabel(lead.source)} className="max-w-full" />
                            </div>
                          </td>
                          <td className="px-3 py-2 align-middle text-xs text-slate-500">
                            {lead.campaign_id && campaignLabelById[lead.campaign_id]
                              ? <HoverText text={formatCampaignOptionLabel(lead.campaign_id)} className="max-w-full">{campaignLabelById[lead.campaign_id]}</HoverText>
                              : '-'}
                          </td>
                          <td className="px-3 py-2 align-middle text-slate-500">
                            <HoverText text={lead.timestamp ? new Date(lead.timestamp).toLocaleString() : '-'} className="max-w-full">
                              <div className="text-xs leading-tight">{lead.timestamp ? new Date(lead.timestamp).toLocaleString() : '-'}</div>
                            </HoverText>
                            {lead.follow_up_due_at && (
                              <HoverText text={`Follow-up: ${new Date(lead.follow_up_due_at).toLocaleDateString()}`} className="mt-0.5 max-w-full">
                                <div className="text-xs text-cyan-400">Follow-up: {new Date(lead.follow_up_due_at).toLocaleDateString()}</div>
                              </HoverText>
                            )}
                          </td>
                          <td className="px-3 py-2 align-middle text-right">
                            <div className="flex items-center justify-end gap-2">
                              <button
                                onClick={() => sendSingleLead(lead)}
                                className="min-w-[74px] rounded-lg bg-white px-3 py-1.5 text-xs font-semibold text-slate-950 shadow-sm shadow-white/10 transition-all hover:bg-slate-200"
                              >
                                Enviar
                              </button>
                            </div>
                          </td>
                          <td className="px-3 py-2 align-middle text-right">
                            <div className="flex items-center justify-end">
                              <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                  <button className="inline-flex min-w-[88px] items-center justify-center gap-1 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs font-medium text-slate-200 transition-colors hover:bg-slate-800">
                                    Acciones
                                    <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
                                  </button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end" className="w-48 border-slate-700 bg-slate-800">
                                  <DropdownMenuLabel className="text-slate-400">@{lead.username}</DropdownMenuLabel>
                                  <DropdownMenuSeparator className="bg-slate-700" />
                                  <DropdownMenuItem
                                    onClick={() => openInstagramProfile(lead.username)}
                                    className="text-xs text-slate-300 focus:bg-slate-700 focus:text-white cursor-pointer"
                                  >
                                    🕵️ Ver Perfil
                                  </DropdownMenuItem>
                                  {accountNeedsRelogin && (
                                    <DropdownMenuItem
                                      onClick={reloginActiveAccount}
                                      disabled={isReloggingAccount}
                                      className="text-xs text-rose-300 focus:bg-rose-500/20 cursor-pointer"
                                    >
                                      {isReloggingAccount ? '🔐 Re-logueando...' : '🔐 Re-loguear cuenta'}
                                    </DropdownMenuItem>
                                  )}
                                  {lead.status.startsWith('Error') && typeof lead.id === 'number' && (
                                    <DropdownMenuItem
                                      onClick={() => updateSingleLeadStatus(lead.id!, 'Listo para contactar', lead.username)}
                                      className="text-xs text-amber-300 focus:bg-amber-500/20 cursor-pointer"
                                    >
                                      ↺ Reactivar
                                    </DropdownMenuItem>
                                  )}
                                  {typeof lead.id === 'number' && (
                                    <>
                                      <DropdownMenuSeparator className="bg-slate-700" />
                                      <DropdownMenuItem
                                        onClick={async () => {
                                          try {
                                            const res = await apiFetch(apiUrl(`/api/leads/${lead.id}`), { method: 'DELETE' });
                                            if (!res.ok) {
                                              const data = await res.json();
                                              toast.error(data.detail || 'No pude eliminar el lead.');
                                              return;
                                            }
                                            await mutateLeads();
                                            toast.success(`Lead @${lead.username} eliminado.`);
                                          } catch {
                                            toast.error('Error eliminando el lead.');
                                          }
                                        }}
                                        className="text-xs text-rose-300 focus:bg-rose-500/20 cursor-pointer"
                                      >
                                        🗑️ Eliminar lead
                                      </DropdownMenuItem>
                                    </>
                                  )}
                                </DropdownMenuContent>
                              </DropdownMenu>
                            </div>
                          </td>
                        </tr>
                      )) : (
                        <tr>
                          <td colSpan={8} className="px-6 py-16 text-center text-slate-500">
                            <div className="flex flex-col items-center justify-center space-y-3">
                              <Users className="w-12 h-12 text-slate-700" />
                              <p>Cargando datos del CRM o la tabla está vacía...</p>
                            </div>
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {currentView === 'message_studio' && (
            <div className="animate-in fade-in slide-in-from-bottom-4 space-y-6">
              <div>
                <div className="flex items-center gap-3">
                  <h2 className="text-3xl font-bold tracking-tight text-slate-100">Message Studio</h2>
                  <button onClick={openHowTo} className="rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs font-medium text-slate-300 hover:border-cyan-500 hover:text-cyan-300">
                    Cómo usarlo
                  </button>
                </div>
                <p className="text-slate-400">Define prompts por etapa y actualiza borradores pendientes en bloque.</p>
              </div>

              <div className="rounded-2xl border border-slate-800 bg-slate-900 p-5 shadow-xl">
                <div className="mb-4 rounded-xl border border-slate-800 bg-slate-950/60 p-4">
                  <p className="text-xs uppercase tracking-wider text-slate-500 inline-flex items-center gap-2">Prompt Maestro <InfoHint text="Afecta tono y enfoque general de toda la secuencia. Las reglas de seguridad siguen fijas en backend." /></p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <button
                      onClick={() => setMasterPromptMode('default')}
                      className={`rounded-lg px-3 py-1.5 text-xs font-medium ${masterPromptMode === 'default' ? 'bg-cyan-600 text-white' : 'bg-slate-800 text-slate-200 hover:bg-slate-700'}`}
                    >
                      Prompt inicial
                    </button>
                    <button
                      onClick={() => setMasterPromptMode('custom')}
                      className={`rounded-lg px-3 py-1.5 text-xs font-medium ${masterPromptMode === 'custom' ? 'bg-cyan-600 text-white' : 'bg-slate-800 text-slate-200 hover:bg-slate-700'}`}
                    >
                      Prompt personalizado
                    </button>
                  </div>
                  <p className="mt-2 text-xs text-slate-400">Define el tono general para toda la secuencia. Las reglas duras de seguridad y calidad siguen fijas en backend.</p>
                  {masterPromptMode === 'custom' && (
                    <textarea
                      value={masterPrompt}
                      onChange={(e) => setMasterPrompt(e.target.value)}
                      rows={3}
                      className="mt-3 w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-500"
                      placeholder="Ej: tono consultivo, profesional, cercano, CTA suave y foco en inmobiliario."
                    />
                  )}
                </div>

                <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
                  <p className="text-xs uppercase tracking-wider text-slate-500">Qué borradores actualizar</p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    {(['Pendiente', 'Listo para contactar', 'Primer contacto', 'Follow-up 1', 'Follow-up 2'] as const).map((status) => (
                      <button
                        key={status}
                        onClick={() => toggleMessageStatus(status)}
                        className={`rounded-lg px-3 py-1.5 text-xs font-medium ${messageStatuses.includes(status) ? 'bg-cyan-600 text-white' : 'bg-slate-800 text-slate-200 hover:bg-slate-700'}`}
                      >
                        {status}
                      </button>
                    ))}
                  </div>
                  <GlowSelect
                    value={messageScopeCampaign}
                    onChange={setMessageScopeCampaign}
                    options={[
                      { value: '', label: 'Todas las campañas' },
                      ...messageCampaignOptions.map((campaignId) => ({ value: campaignId, label: formatCampaignOptionLabel(campaignId) })),
                    ]}
                    className="mt-3 min-w-[220px] max-w-sm"
                  />
                  <p className="mt-2 text-xs text-slate-400">Aquí solo actualizas borradores. `Pendiente` también entra y usa el mensaje de primer contacto.</p>
                  <p className="mt-1 text-xs text-slate-500">Leads afectados: {messageScopeLeadIds.length}</p>
                </div>

                <div className="mt-4 grid grid-cols-1 gap-3 xl:grid-cols-3">
                  <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                    <p className="text-xs font-semibold uppercase tracking-wider text-cyan-300">Primer contacto</p>
                    <p className="mt-1 text-[11px] text-slate-500">Apertura inicial, humana y corta.</p>
                    <textarea
                      value={messagePrompt}
                      onChange={(e) => setMessagePrompt(e.target.value)}
                      rows={4}
                      className="mt-2 w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-500"
                      placeholder="Oferta, tono y CTA suave."
                    />
                  </div>
                  <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                    <p className="text-xs font-semibold uppercase tracking-wider text-violet-300">Follow-up 1</p>
                    <p className="mt-1 text-[11px] text-slate-500">Continuación natural, sin insistir.</p>
                    <textarea
                      value={followUp1Prompt}
                      onChange={(e) => setFollowUp1Prompt(e.target.value)}
                      rows={4}
                      className="mt-2 w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-violet-500"
                      placeholder="Retoma el hilo y abre respuesta."
                    />
                  </div>
                  <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                    <p className="text-xs font-semibold uppercase tracking-wider text-amber-300">Follow-up 2</p>
                    <p className="mt-1 text-[11px] text-slate-500">Último mensaje, cierre elegante.</p>
                    <textarea
                      value={followUp2Prompt}
                      onChange={(e) => setFollowUp2Prompt(e.target.value)}
                      rows={4}
                      className="mt-2 w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-amber-500"
                      placeholder="Cierre final sin presión."
                    />
                  </div>
                </div>

                {(isPreparingDrafts || isSavingDrafts) && (
                  <div className="mt-4 rounded-xl border border-cyan-500/20 bg-cyan-500/5 px-4 py-3 text-sm text-cyan-100">
                    <div className="flex items-center gap-3">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      <span>{draftProgressLabel || 'Procesando borradores...'}</span>
                    </div>
                  </div>
                )}

                <div className="mt-4 flex flex-wrap items-center gap-2">
                  <button onClick={() => { if (requireAiFeature(hasAiForMessages)) void previewPendingDraftsFromMessages(); }} disabled={isPreparingDrafts || isSavingDrafts || messageScopeLeadIds.length === 0} title={!hasAiForMessages ? aiBlockedReason : undefined} className={`rounded-lg px-3 py-1.5 text-xs font-medium disabled:opacity-40 ${hasAiForMessages ? 'bg-slate-800 text-slate-100 hover:bg-slate-700' : 'bg-rose-500/15 text-rose-200 ring-1 ring-rose-500/30 hover:bg-rose-500/20'}`}>
                    {isPreparingDrafts ? 'Generando...' : 'Generar muestra IA'}
                  </button>
                  <button onClick={() => { if (requireAiFeature(hasAiForMessages)) void updatePendingDraftsFromMessages(); }} disabled={isPreparingDrafts || isSavingDrafts || messageScopeLeadIds.length === 0} title={!hasAiForMessages ? aiBlockedReason : undefined} className={`rounded-lg px-3 py-1.5 text-xs font-semibold disabled:opacity-40 ${hasAiForMessages ? 'bg-white text-slate-950 hover:bg-slate-200' : 'bg-rose-500/15 text-rose-200 ring-1 ring-rose-500/30 hover:bg-rose-500/20'}`}>
                    {isSavingDrafts ? 'Actualizando...' : 'Actualizar borradores'}
                  </button>
                  <button onClick={() => setCurrentView('crm')} className="rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700">
                    Volver al CRM
                  </button>
                </div>
              </div>

              {messagePreviews.length > 0 && (
                <div className="rounded-2xl border border-slate-800 bg-slate-900 p-5 shadow-xl">
                  <div className="flex items-center justify-between gap-3">
                    <h3 className="text-lg font-semibold text-slate-100">Vista previa IA</h3>
                    <Badge variant="outline" className="border-cyan-500/30 text-cyan-300">{messagePreviews.length} borrador(es)</Badge>
                  </div>
                  <div className="mt-4 grid grid-cols-1 gap-3">
                    {messagePreviews.slice(0, 6).map((preview) => (
                      <div key={preview.id} className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                        <div className="flex items-center justify-between gap-3">
                          <p className="text-sm font-medium text-slate-100">@{preview.username}</p>
                          <div className="flex items-center gap-2">
                            {preview.variant && <Badge variant="outline" className="border-slate-700 text-slate-300">{preview.variant}</Badge>}
                            <Badge variant="outline" className="border-cyan-500/30 text-cyan-300">preview</Badge>
                          </div>
                        </div>
                        <p className="mt-2 text-sm text-slate-300">{preview.message}</p>
                        {preview.rationale && <p className="mt-2 text-xs text-slate-500">{preview.rationale}</p>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {currentView === 'api_keys' && (
            <div className="animate-in fade-in slide-in-from-bottom-4 space-y-6">
              <div className="rounded-3xl border border-slate-800 bg-[radial-gradient(circle_at_top,_rgba(56,189,248,0.12),_transparent_45%),linear-gradient(180deg,rgba(15,23,42,0.92),rgba(2,6,23,0.98))] p-8 shadow-2xl">
                <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
                  <div className="max-w-2xl">
                    <p className="text-xs font-semibold uppercase tracking-[0.25em] text-cyan-300">API Keys</p>
                    <h2 className="mt-3 text-3xl font-bold tracking-tight text-slate-100">Activa las funciones con IA por workspace</h2>
                    <p className="mt-3 text-sm leading-relaxed text-slate-300">Botardium funciona manualmente sin IA. Si quieres Magic Box, borradores automáticos y regeneración inteligente, guarda aquí tus claves. La opción recomendada para empezar es <span className="font-semibold text-cyan-200">Google AI Studio</span>, que puede usarse gratis en muchos casos.</p>
                  </div>
                  <div className="rounded-2xl border border-cyan-500/20 bg-cyan-500/10 px-4 py-3 text-xs text-cyan-100">
                    Las claves quedan asociadas a <span className="font-semibold">{currentUserEmail || 'este workspace'}</span> en esta computadora.
                  </div>
                </div>
              </div>

              <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
                <div className="rounded-3xl border border-slate-800 bg-slate-900 p-6 shadow-xl">
                  <h3 className="text-lg font-semibold text-slate-100">Proveedores disponibles</h3>
                  <div className="mt-5 space-y-4">
                    <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <p className="font-semibold text-slate-100">Google AI Studio</p>
                          <p className="mt-1 text-sm text-slate-400">Ideal para empezar sin costo alto. Botardium la usa para Magic Box y Message Studio cuando está disponible.</p>
                        </div>
                        <Badge variant="outline" className={aiSettings?.google_configured ? 'border-emerald-500/30 text-emerald-300' : 'border-rose-500/30 text-rose-300'}>{aiSettings?.google_configured ? 'Conectada' : 'Falta key'}</Badge>
                      </div>
                      <input value={googleApiKeyInput} onChange={(e) => setGoogleApiKeyInput(e.target.value)} placeholder={aiSettings?.google_api_key ? `Actual: ${aiSettings.google_api_key}` : 'Pega tu GOOGLE_API_KEY'} className="mt-4 w-full rounded-xl border border-slate-800 bg-slate-900 px-4 py-3 text-sm text-slate-100 outline-none focus:border-cyan-500" />
                    </div>
                    <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <p className="font-semibold text-slate-100">OpenAI</p>
                          <p className="mt-1 text-sm text-slate-400">Opcional. Puede servirte como respaldo o para mantener la calidad del flujo IA si ya tienes crédito allí.</p>
                        </div>
                        <Badge variant="outline" className={aiSettings?.openai_configured ? 'border-emerald-500/30 text-emerald-300' : 'border-slate-700 text-slate-400'}>{aiSettings?.openai_configured ? 'Conectada' : 'Opcional'}</Badge>
                      </div>
                      <input value={openAiApiKeyInput} onChange={(e) => setOpenAiApiKeyInput(e.target.value)} placeholder={aiSettings?.openai_api_key ? `Actual: ${aiSettings.openai_api_key}` : 'Pega tu OPENAI_API_KEY'} className="mt-4 w-full rounded-xl border border-slate-800 bg-slate-900 px-4 py-3 text-sm text-slate-100 outline-none focus:border-cyan-500" />
                    </div>
                  </div>
                  <div className="mt-5 flex flex-wrap gap-3">
                    <button onClick={saveAiKeys} disabled={isSavingAiKeys} className="rounded-xl bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-500 disabled:opacity-50">{isSavingAiKeys ? 'Guardando...' : 'Guardar API Keys'}</button>
                    <button onClick={() => { setGoogleApiKeyInput(''); setOpenAiApiKeyInput(''); }} className="rounded-xl bg-slate-800 px-4 py-2 text-sm font-medium text-slate-200 hover:bg-slate-700">Limpiar formulario</button>
                  </div>
                </div>

                <div className="space-y-6">
                  <div className="rounded-3xl border border-slate-800 bg-slate-900 p-6 shadow-xl">
                    <h3 className="text-lg font-semibold text-slate-100">Qué desbloquean</h3>
                    <div className="mt-4 space-y-3 text-sm text-slate-300">
                      <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
                        <p className="font-medium text-slate-100">Magic Box</p>
                        <p className="mt-1 text-slate-400">Genera una ruta inteligente de scraping y propone hashtags iniciales para tu nicho.</p>
                      </div>
                      <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
                        <p className="font-medium text-slate-100">Message Studio</p>
                        <p className="mt-1 text-slate-400">Crea previews, actualiza borradores en lote y regenera mensajes por lead.</p>
                      </div>
                    </div>
                  </div>
                  <div className="rounded-3xl border border-amber-500/20 bg-amber-500/10 p-6 shadow-xl">
                    <h3 className="text-lg font-semibold text-amber-100">Sin API keys</h3>
                    <ul className="mt-4 space-y-2 text-sm text-amber-50/90">
                      <li>- Puedes conectar cuentas, scrapear, usar CRM y ejecutar campañas manuales.</li>
                      <li>- Las funciones con IA quedan deshabilitadas y Botardium te traerá a esta pantalla cuando intentes usarlas.</li>
                      <li>- No hace falta tocar `.env`; esta configuración es local al workspace.</li>
                    </ul>
                  </div>
                  <div className="rounded-3xl border border-slate-800 bg-slate-900 p-6 shadow-xl">
                    <h3 className="text-lg font-semibold text-slate-100">Workspace portátil</h3>
                    <p className="mt-2 text-sm text-slate-400">Exporta este workspace para mover CRM, campañas, cuentas y sesiones a otra computadora. Luego impórtalo desde la pantalla inicial.</p>
                    <div className="mt-4 flex flex-wrap gap-3">
                      <button onClick={() => { void exportWorkspace(); }} disabled={isExportingWorkspace || !currentUserId} className="rounded-xl bg-white px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-slate-200 disabled:opacity-50">
                        {isExportingWorkspace ? 'Exportando...' : 'Exportar workspace'}
                      </button>
                      <button onClick={() => { void importWorkspace(); }} disabled={isImportingWorkspace} className="rounded-xl border border-slate-700 bg-slate-950 px-4 py-2 text-sm font-medium text-slate-200 hover:border-cyan-500 hover:text-cyan-200 disabled:opacity-50">
                        {isImportingWorkspace ? 'Importando...' : 'Importar workspace'}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {currentView === 'guide' && (
            <div className="animate-in fade-in slide-in-from-bottom-4 space-y-8">
              <div className="rounded-3xl border border-slate-800 bg-[radial-gradient(circle_at_top_left,_rgba(34,197,94,0.10),_transparent_30%),radial-gradient(circle_at_top_right,_rgba(59,130,246,0.10),_transparent_35%),linear-gradient(180deg,rgba(15,23,42,0.95),rgba(2,6,23,0.98))] p-8 shadow-2xl">
                <p className="text-xs font-semibold uppercase tracking-[0.25em] text-emerald-300">Cómo usar Botardium</p>
                <h2 className="mt-3 text-4xl font-bold tracking-tight text-slate-100">Guía rápida para operar sin mezclar datos ni quemar cuentas</h2>
                <p className="mt-4 max-w-3xl text-sm leading-relaxed text-slate-300">Botardium es una app local-first. Cada workspace guarda su propio CRM, campañas, cuentas conectadas y sesiones en esta computadora. Puedes usar la app de forma manual o activar IA desde <span className="font-semibold text-cyan-200">API Keys</span>.</p>
              </div>

              <div className="grid gap-6 xl:grid-cols-4">
                {[
                  ['1', 'Elige tu workspace', 'Abre el workspace correcto antes de tocar cuentas o campañas. Así no mezclas leads entre operaciones.'],
                  ['2', 'Conecta una cuenta IG', 'Botardium abre un navegador real para login y 2FA. La sesión queda guardada por workspace.'],
                  ['3', 'Scrapea y califica', 'Lanza campañas desde Dashboard y revisa el resultado en CRM antes de contactar.'],
                  ['4', 'Contacta con control', 'Usa Message Studio si tienes API keys o edita manualmente antes de enviar.'],
                ].map(([step, title, copy]) => (
                  <div key={step} className="rounded-3xl border border-slate-800 bg-slate-900 p-5 shadow-xl">
                    <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-emerald-500/15 text-lg font-bold text-emerald-300">{step}</div>
                    <h3 className="mt-4 text-lg font-semibold text-slate-100">{title}</h3>
                    <p className="mt-2 text-sm leading-relaxed text-slate-400">{copy}</p>
                  </div>
                ))}
              </div>

              <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
                <div className="rounded-3xl border border-slate-800 bg-slate-900 p-6 shadow-xl">
                  <h3 className="text-xl font-semibold text-slate-100">Flujo operativo recomendado</h3>
                  <div className="mt-5 space-y-4 text-sm text-slate-300">
                    <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4"><span className="font-semibold text-slate-100">Cuentas:</span> conecta la cuenta emisora, revisa salud y reloguea si la sesión venció.</div>
                    <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4"><span className="font-semibold text-slate-100">Dashboard:</span> define source, filtros y límite; una campaña equivale a un source.</div>
                    <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4"><span className="font-semibold text-slate-100">CRM:</span> revisa leads, mueve a <span className="text-slate-100">Listo para contactar</span> y evita estados cerrados.</div>
                    <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4"><span className="font-semibold text-slate-100">Message Studio:</span> si tienes API keys, genera borradores; si no, trabaja manualmente.</div>
                    <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4"><span className="font-semibold text-slate-100">Campañas:</span> monitorea logs, fuentes y rendimiento antes de relanzar otra búsqueda.</div>
                  </div>
                </div>
                <div className="space-y-6">
                  <div className="rounded-3xl border border-slate-800 bg-slate-900 p-6 shadow-xl">
                    <h3 className="text-xl font-semibold text-slate-100">Qué requiere IA</h3>
                    <div className="mt-4 space-y-3 text-sm text-slate-300">
                      <p><span className="font-semibold text-slate-100">Magic Box:</span> sí, necesita API keys.</p>
                      <p><span className="font-semibold text-slate-100">Borradores automáticos:</span> sí, necesita API keys.</p>
                      <p><span className="font-semibold text-slate-100">Scraping, CRM, campañas y envío manual:</span> no, funcionan sin IA.</p>
                    </div>
                  </div>
                  <div className="rounded-3xl border border-slate-800 bg-slate-900 p-6 shadow-xl">
                    <h3 className="text-xl font-semibold text-slate-100">Buenas prácticas</h3>
                    <ul className="mt-4 space-y-2 text-sm text-slate-300">
                      <li>- Mantén un workspace por operación, cliente o proyecto.</li>
                      <li>- No envíes desde estados cerrados ni desde sesión fría si la app te avisa.</li>
                      <li>- Si una cuenta cae en relogin, rehace la sesión antes de insistir.</li>
                      <li>- No repitas scraping idéntico si ya tienes suficientes leads útiles en el CRM.</li>
                    </ul>
                  </div>
                </div>
              </div>

              <div className="rounded-3xl border border-slate-800 bg-slate-900 p-6 shadow-xl">
                <h3 className="text-xl font-semibold text-slate-100">Preguntas frecuentes</h3>
                <div className="mt-5 grid gap-4 xl:grid-cols-2">
                  <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4 text-sm text-slate-300"><span className="font-semibold text-slate-100">¿Dónde viven mis datos?</span><p className="mt-2">En esta PC, dentro del storage local de Botardium por workspace.</p></div>
                  <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4 text-sm text-slate-300"><span className="font-semibold text-slate-100">¿Necesito API keys para usar la app?</span><p className="mt-2">No. Solo para Magic Box y funciones IA de mensajes.</p></div>
                  <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4 text-sm text-slate-300"><span className="font-semibold text-slate-100">¿Los follow-ups salen automáticos?</span><p className="mt-2">No. Siguen siendo manuales para que mantengas control operativo.</p></div>
                  <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4 text-sm text-slate-300"><span className="font-semibold text-slate-100">¿Qué hago si Instagram pide 2FA?</span><p className="mt-2">Completa el challenge en el navegador visible que abre Botardium; la app espera hasta guardar la sesión.</p></div>
                </div>
              </div>
            </div>
          )}

          {currentView === 'campaigns' && (
            <div className="animate-in fade-in slide-in-from-bottom-4">
              <div className="mb-8">
                <div className="flex items-center gap-3">
                  <h2 className="text-3xl font-bold tracking-tight text-slate-100">Campañas</h2>
                  <button onClick={openHowTo} className="rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs font-medium text-slate-300 hover:border-cyan-500 hover:text-cyan-300">
                    Cómo usarlo
                  </button>
                </div>
                <p className="text-slate-400">Supervisa tus procesos de envío de DM y extracciones automáticas.</p>
              </div>

              {activeCampaigns.length > 0 ? (
                <div className="grid grid-cols-1 xl:grid-cols-[1.2fr_0.8fr] gap-6">
                  <div className="bg-slate-900 border border-slate-800 rounded-3xl overflow-hidden shadow-xl">
                    <div className="p-5 border-b border-slate-800 bg-slate-800/30 flex items-center justify-between">
                      <div>
                        <h3 className="font-semibold text-slate-100">Pipeline de Ejecucion</h3>
                        <p className="text-sm text-slate-400 mt-1">Las campanas lanzadas desde el panel quedan registradas aqui.</p>
                      </div>
                      <Badge className="bg-emerald-500/10 text-emerald-400 border-none">{activeCampaigns.length} activa(s)</Badge>
                    </div>
                    <div className="divide-y divide-slate-800">
                      {sortedCampaigns.map((campaign) => {
                        const isActive = campaign.status === 'running' || campaign.status === 'warmup' || campaign.status === 'paused';
                        const isExpanded = expandedCampaigns[campaign.id] ?? isActive;
                        const isDeletingCampaign = !!campaignDeleteLoading[campaign.id];
                        const isConfirmingCampaignDelete = !!campaignDeleteConfirming[campaign.id];
                        return (
                          <div key={campaign.id} className="p-5">
                            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                              <div>
                                <div className="flex items-center gap-3 flex-wrap">
                                  <button
                                    onClick={() => setExpandedCampaigns((prev) => ({ ...prev, [campaign.id]: !isExpanded }))}
                                    className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-slate-700 bg-slate-900 text-slate-300 hover:border-cyan-500 hover:text-cyan-300"
                                    title={isExpanded ? 'Colapsar campaña' : 'Expandir campaña'}
                                  >
                                    <ChevronDown className={`h-4 w-4 transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
                                  </button>
                                  <div>
                                    {editingCampaignId === campaign.id ? (
                                      <div className="flex flex-wrap items-center gap-2">
                                        <input
                                          type="text"
                                          value={editingCampaignName}
                                          onChange={(e) => setEditingCampaignName(e.target.value.slice(0, 80))}
                                          className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm text-slate-100 outline-none focus:border-cyan-500"
                                          autoFocus
                                        />
                                        <button onClick={() => saveCampaignName(campaign.id)} className="rounded-lg bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-cyan-500">Guardar</button>
                                        <button onClick={() => { setEditingCampaignId(null); setEditingCampaignName(''); }} className="rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700">Cancelar</button>
                                      </div>
                                    ) : (
                                      <div className="flex items-center gap-2">
                                        <p className="text-lg font-semibold text-slate-100">{campaign.campaignName}</p>
                                        <button
                                          onClick={() => { setEditingCampaignId(campaign.id); setEditingCampaignName(campaign.campaignName); }}
                                          className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-[11px] font-medium text-slate-300 hover:border-cyan-500 hover:text-cyan-300"
                                        >
                                          Renombrar
                                        </button>
                                      </div>
                                    )}
                                    <p className="text-xs text-slate-500">@{campaign.username} · {campaign.id.slice(0, 8)}</p>
                                  </div>
                                  <Badge variant="secondary" className={`${campaign.status === 'needs_review' ? 'bg-amber-500/15 text-amber-300' : campaign.status === 'paused' ? 'bg-slate-700/80 text-slate-200' : 'bg-purple-500/15 text-purple-300'}`}>{formatCampaignStatusLabel(campaign.status)}</Badge>
                                  <span className="text-xs text-slate-500">Limite {campaign.limit}</span>
                                </div>
                                <p className="text-sm text-slate-400 mt-2">{cleanOperatorMessage(campaign.currentAction)}</p>
                                <div className="mt-3 w-full max-w-xl">
                                  <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
                                    <span>Progreso visible</span>
                                    <span>{campaign.progress}%</span>
                                  </div>
                                  <div className="h-2 rounded-full bg-slate-800 overflow-hidden">
                                    <div className="h-full rounded-full bg-gradient-to-r from-cyan-400 to-emerald-400 transition-all" style={{ width: `${campaign.progress}%` }}></div>
                                  </div>
                                </div>
                                <p className="text-xs text-slate-500 mt-2">Modo: {campaign.executionMode === 'real' ? 'real' : 'test'}</p>
                                {campaign.filters && (
                                  <p className="text-xs text-slate-500 mt-1">
                                    Filtros: min followers {campaign.filters.min_followers ?? 0}, min posts {campaign.filters.min_posts ?? 0}, anti-ruido {campaign.filters.require_coherence === false ? 'off' : 'on'}
                                  </p>
                                )}
                                {isExpanded && (
                                  <>
                                    <div className="mt-4 flex flex-wrap gap-2">
                                      {campaign.sources.map((source, index) => {
                                        const prefix = source.type === 'hashtag' ? '#' : source.type === 'followers' ? '@' : '';
                                        return (
                                          <Badge key={`${campaign.id}-${index}`} variant="outline" className="border-slate-700 text-slate-300">
                                            {source.type}: {prefix}{source.target}
                                          </Badge>
                                        );
                                      })}
                                    </div>
                                    <div className="mt-4 rounded-2xl border border-slate-800 bg-slate-950/50 p-4">
                                      <p className="text-xs uppercase tracking-wider text-slate-500 mb-2">Proximo paso</p>
                                      <p className="text-sm text-slate-300">
                                        {campaign.status === 'draft' && 'Puedes ejecutar scraping ahora. El calentamiento de sesion se hace luego desde CRM antes de contactar.'}
                                        {campaign.status === 'warmup' && 'Espera a que termine el warmup y luego lanza el scraping.'}
                                        {campaign.status === 'ready' && 'Ya puedes arrancar la extraccion con este mix de targeting.'}
                                        {campaign.status === 'paused' && 'La campaña quedó pausada y conserva su progreso. Reanuda cuando quieras.'}
                                        {campaign.status === 'needs_review' && 'Revisá los hashtags: la campaña encontró fuentes sin volumen suficiente.'}
                                        {campaign.status === 'running' && 'La campana ya esta corriendo. Puedes detenerla o eliminarla del panel.'}
                                        {campaign.status === 'completed' && (campaign.executionMode === 'real'
                                          ? 'El extractor real termino. Si el CRM no crecio, Instagram no devolvio candidatos validos o la fuente usada no produjo leads utiles.'
                                          : 'El pipeline de test termino. No toca Instagram ni escribe leads en el CRM.')}
                                      </p>
                                    </div>
                                    <div className="mt-4 rounded-2xl border border-slate-800 bg-slate-950/50 p-4">
                                      <p className="text-xs uppercase tracking-wider text-slate-500 mb-3">Ultimos eventos</p>
                                      <div className="space-y-2">
                                        {campaign.logs.length > 0 ? campaign.logs.slice(0, 4).map((log, index) => (
                                          <div key={`${campaign.id}-log-${index}`} className="flex items-start justify-between gap-3 rounded-xl border border-slate-800/70 bg-slate-950/40 px-3 py-2">
                                            <div className="min-w-0">
                                              <p className={`text-sm font-semibold ${formatCampaignLog(log.message).tone === 'warn' ? 'text-amber-200' : formatCampaignLog(log.message).tone === 'ok' ? 'text-emerald-200' : 'text-cyan-200'}`}>
                                                {formatCampaignLog(log.message).title}
                                              </p>
                                              <p className="text-xs text-slate-300 mt-1 break-words">{formatCampaignLog(log.message).detail}</p>
                                            </div>
                                            <span className="text-xs text-slate-500 whitespace-nowrap">{new Date(log.timestamp * 1000).toLocaleTimeString()}</span>
                                          </div>
                                        )) : (
                                          <p className="text-sm text-slate-500">Todavia no hay eventos registrados.</p>
                                        )}
                                      </div>
                                    </div>
                                    {Object.keys(campaign.sourceStats).length > 0 && (
                                      <div className="mt-4 rounded-2xl border border-slate-800 bg-slate-950/50 p-4">
                                        <p className="text-xs uppercase tracking-wider text-slate-500 mb-3">Rendimiento por source</p>
                                        <div className="space-y-3">
                                          {Object.entries(campaign.sourceStats).map(([label, stats]) => (
                                            <div key={label} className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
                                              <div className="flex items-center justify-between gap-3">
                                                <span className="text-sm font-medium text-slate-200">{label}</span>
                                                <Badge variant="outline" className={`${stats.status === 'invalid' ? 'border-amber-500/30 text-amber-300' : 'border-slate-700 text-slate-300'}`}>{formatSourceStatusLabel(stats.status)}</Badge>
                                              </div>
                                              <div className="mt-2 flex flex-wrap gap-2 text-xs">
                                                <span className="rounded-full bg-emerald-500/10 px-2 py-1 text-emerald-300">Aceptados: {stats.accepted}</span>
                                                {typeof stats.posts_seen === 'number' && (
                                                  <span className="rounded-full bg-cyan-500/10 px-2 py-1 text-cyan-300">Posts vistos: {stats.posts_seen}</span>
                                                )}
                                                {typeof stats.authors_seen === 'number' && (
                                                  <span className="rounded-full bg-indigo-500/10 px-2 py-1 text-indigo-300">Autores vistos: {stats.authors_seen}</span>
                                                )}
                                                {typeof stats.profile_errors === 'number' && stats.profile_errors > 0 && (
                                                  <span className="rounded-full bg-amber-500/10 px-2 py-1 text-amber-300">Perfiles no legibles: {stats.profile_errors}</span>
                                                )}
                                                {Object.entries(stats.rejected || {}).slice(0, 3).map(([reason, count]) => (
                                                  <span key={`${label}-${reason}`} className="rounded-full bg-rose-500/10 px-2 py-1 text-rose-300">{formatRejectionReason(reason)}: {count}</span>
                                                ))}
                                              </div>
                                              {typeof stats.error === 'string' && stats.error ? (
                                                <div className="mt-2 rounded-lg border border-amber-500/20 bg-amber-500/10 px-2.5 py-2">
                                                  <p className="text-xs font-semibold text-amber-200">Que pasó</p>
                                                  <p className="text-xs text-amber-100 mt-1">{cleanOperatorMessage(stats.error)}</p>
                                                </div>
                                              ) : null}
                                            </div>
                                          ))}
                                        </div>
                                      </div>
                                    )}
                                  </>
                                )}
                              </div>
                              <div className="lg:text-right">
                                <p className="text-xs uppercase tracking-wider text-slate-500">Creada</p>
                                <p className="text-sm text-slate-300 mt-1">{new Date(campaign.createdAt * 1000).toLocaleString()}</p>
                                {campaign.status === 'completed' && (
                                  <button
                                    onClick={() => { setSelectedCampaignFilter(campaign.id); setCurrentView('crm'); }}
                                    className="mt-4 w-full rounded-xl bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 lg:w-auto"
                                  >
                                    Ir al CRM
                                  </button>
                                )}
                                <div className="mt-4 flex flex-wrap gap-2 lg:justify-end">
                                  {campaign.status === 'warmup' && (
                                    <button
                                      onClick={() => campaignAction(campaign.id, 'finish_warmup')}
                                      className="rounded-xl bg-emerald-500/15 px-4 py-2 text-sm font-medium text-emerald-300 hover:bg-emerald-500/25"
                                    >
                                      Forzar Ready
                                    </button>
                                  )}
                                  {(campaign.status === 'draft' || campaign.status === 'ready' || campaign.status === 'paused') && (
                                    <button
                                      onClick={() => campaignAction(campaign.id, 'start_scraping')}
                                      className="rounded-xl bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-500"
                                    >
                                      {campaign.status === 'paused' ? 'Reanudar Scraping' : 'Iniciar Scraping'}
                                    </button>
                                  )}
                                  {campaign.status === 'needs_review' && (
                                    <button
                                      onClick={() => setCurrentView('dashboard')}
                                      className="rounded-xl bg-amber-500/15 px-4 py-2 text-sm font-medium text-amber-200 hover:bg-amber-500/25"
                                    >
                                      Revisar hashtags
                                    </button>
                                  )}
                                  {campaign.status === 'running' && (
                                    <button
                                      onClick={() => campaignAction(campaign.id, 'pause')}
                                      className="rounded-xl bg-slate-800 px-4 py-2 text-sm font-medium text-slate-200 hover:bg-slate-700"
                                    >
                                      Pausar
                                    </button>
                                  )}
                                  <button
                                    onClick={() => { void handleCampaignDelete(campaign.id, campaign.campaignName); }}
                                    onBlur={() => { if (!isDeletingCampaign) clearCampaignDeleteConfirm(campaign.id); }}
                                    disabled={isDeletingCampaign}
                                    className={`rounded-xl border px-4 py-2 text-sm font-medium transition-colors ${
                                      isDeletingCampaign
                                        ? 'cursor-wait border-slate-600 bg-slate-700/60 text-slate-200'
                                        : isConfirmingCampaignDelete
                                          ? 'border-rose-400/60 bg-rose-500/20 text-rose-100 hover:bg-rose-500/30'
                                          : 'border-rose-500/30 text-rose-300 hover:bg-rose-500/10'
                                    }`}
                                  >
                                    {isDeletingCampaign ? (
                                      <span className="inline-flex items-center gap-2">
                                        <Loader2 className="h-4 w-4 animate-spin" />
                                        Eliminando...
                                      </span>
                                    ) : isConfirmingCampaignDelete ? 'Confirmar eliminar' : 'Eliminar'}
                                  </button>
                                </div>
                              </div>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>

                  <div className="bg-slate-900 border border-slate-800 rounded-3xl p-6 shadow-xl">
                    <h3 className="text-lg font-semibold text-slate-100">Que hago ahora?</h3>
                    <p className="text-sm text-slate-400 mt-1">Botardium ahora te guia por pasos para que nunca te quedes clavado en esta pantalla.</p>
                    <div className="mt-5 space-y-3">
                      <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
                        <p className="text-xs uppercase tracking-wider text-slate-500 mb-2">Secuencia sugerida</p>
                        <p className="text-sm text-slate-300">1. Revisa si la campana necesita warmup o si vas sin warmup.</p>
                        <p className="text-sm text-slate-300">2. Haz clic en el CTA disponible dentro de la campana.</p>
                        <p className="text-sm text-slate-300">3. Cuando el estado pase a lista, inicia scraping.</p>
                      </div>
                      <button
                        onClick={() => setCurrentView('dashboard')}
                        className="w-full bg-purple-600 hover:bg-purple-500 text-white font-medium px-6 py-3 rounded-xl transition-colors"
                      >
                        Ajustar Campana
                      </button>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="bg-slate-900 border border-slate-800 border-dashed rounded-3xl p-16 flex flex-col items-center justify-center text-center">
                  <MessageSquare className="w-16 h-16 text-slate-700 mb-4" />
                  <h3 className="text-xl font-semibold text-slate-200 mb-2">No hay campañas corriendo</h3>
                  <p className="text-slate-500 max-w-sm">Dirigete al Dashboard, usa la Busqueda Inteligente y combina hashtag, followers o location antes de lanzar.</p>
                  <button
                    onClick={() => setCurrentView('dashboard')}
                    className="mt-6 bg-purple-600 hover:bg-purple-500 text-white font-medium px-6 py-2.5 rounded-xl transition-colors"
                  >
                    Ir al Dashboard
                  </button>
                </div>
              )}
            </div>
          )}

          </div>
        </div>
      </div>
    </main>
  );
}
