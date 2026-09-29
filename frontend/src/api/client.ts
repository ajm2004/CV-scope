import { recognitionToken } from "../lib/recognitionToken";
import type {
  AccessToken,
  AnomalyAssistantView,
  AnomalyRecord,
  AnomalyTestResult,
  LLMSettings,
  LocalJob,
  LocalSetupStatus,
  AuditRow,
  Camera,
  CameraInput,
  EnrollmentAnalysis,
  EnrollmentResult,
  EventRecord,
  Evaluation,
  Experiment,
  ExperimentInput,
  HardwareReport,
  InstallJob,
  LicenseSummary,
  ModelInfo,
  Page,
  ParsedPlate,
  PersonInput,
  Principal,
  Project,
  RecognitionEvent,
  RecognitionImpact,
  RecognitionPerson,
  RecognitionSettingsResponse,
  RecognitionStatus,
  RecognitionVehicle,
  RecommendationSet,
  Recording,
  Run,
  RunDiagnostics,
  Scene,
  SceneDocument,
  SettingDefinition,
  Site,
  SystemStatus,
  TrackSummary,
  TrackerInfo,
  VehicleInput,
  Video,
  EnrollmentCheck,
  FeedbackSummary,
  IdentifyResult,
  LiveEntity,
  ResolvedNames,
  TeachResult,
} from "./types";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(method: string, path: string, body?: unknown, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {};
  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  // The licensed recognition API is authenticated with its own token
  const rtoken = path.startsWith("/api/recognition") ? recognitionToken() : null;
  if (rtoken) headers["X-Recognition-Token"] = rtoken;
  const res = await fetch(path, { method, headers, body: payload, ...init });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail ?? j;
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return (await res.json()) as T;
  return (await res.text()) as unknown as T;
}

const get = <T>(path: string) => request<T>("GET", path);
const post = <T>(path: string, body?: unknown) => request<T>("POST", path, body);
const put = <T>(path: string, body?: unknown) => request<T>("PUT", path, body);
const del = <T>(path: string) => request<T>("DELETE", path);

function qs(params: Record<string, unknown>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const api = {
  system: {
    status: () => get<SystemStatus>("/api/system/status"),
    setupComplete: () => post<{ ok: boolean }>("/api/system/setup-complete"),
    load: () => get<Record<string, unknown>>("/api/system/load"),
    privacy: () => get<{ stored: { item: string; stored: boolean; detail: string }[]; retention_days: number; data_dir: string }>("/api/system/privacy"),
    loadEstimate: (streams: Record<string, unknown>[]) => post<Record<string, unknown>>("/api/system/load-estimate", { streams }),
  },
  hardware: {
    get: (refresh = false) => get<HardwareReport>(`/api/hardware${refresh ? "?refresh=true" : ""}`),
    recommendations: () => get<RecommendationSet>("/api/hardware/recommendations"),
    runtimes: (device = "auto", provider = "auto") => get<{ runtimes: HardwareReport["runtimes"]; auto_choice: Record<string, unknown> | null; error: string | null }>(`/api/hardware/runtimes${qs({ device, provider })}`),
    recognitionImpact: (params: { face?: boolean; plate?: boolean; face_stack?: string; model_id?: string | null; processing_fps?: number } = {}) => get<RecognitionImpact>(`/api/hardware/recognition-impact${qs(params)}`),
  },
  models: {
    list: () => get<{ models: ModelInfo[]; recommendations: RecommendationSet; trackers: TrackerInfo[] }>("/api/models"),
    install: (id: string) => post<InstallJob>(`/api/models/${id}/install`),
    remove: (id: string) => del<{ removed: boolean }>(`/api/models/${id}`),
    job: (jobId: string) => get<InstallJob & { results?: Record<string, unknown> }>(`/api/models/jobs/${jobId}`),
    jobs: () => get<{ install: InstallJob[]; benchmark: Record<string, unknown>[] }>("/api/models/jobs"),
    benchmark: (id: string, body: { device?: string; image_size?: number | null; video_id?: number | null; tracker_id?: string; tracker_settings?: Record<string, unknown> }) => post<Record<string, unknown>>(`/api/models/${id}/benchmark`, body),
    benchmarks: () => get<Record<string, unknown>[]>("/api/models/benchmarks"),
  },
  settings: {
    get: () => get<{ values: Record<string, unknown>; definitions: SettingDefinition[]; environment: Record<string, unknown> }>("/api/settings"),
    update: (values: Record<string, unknown>) => put<{ values: Record<string, unknown> }>("/api/settings", { values }),
  },
  projects: {
    list: () => get<Project[]>("/api/projects"),
    get: (id: number) => get<Project>(`/api/projects/${id}`),
    create: (body: { name: string; description?: string; tags?: string[] }) => post<Project>("/api/projects", body),
    update: (id: number, body: { name: string; description?: string; tags?: string[] }) => put<Project>(`/api/projects/${id}`, body),
    remove: (id: number) => del<void>(`/api/projects/${id}`),
    sites: (id: number) => get<Site[]>(`/api/projects/${id}/sites`),
    createSite: (id: number, body: { name: string; description?: string }) => post<Site>(`/api/projects/${id}/sites`, body),
    removeSite: (id: number, siteId: number) => del<void>(`/api/projects/${id}/sites/${siteId}`),
  },
  cameras: {
    list: (projectId?: number) => get<Camera[]>(`/api/cameras${qs({ project_id: projectId })}`),
    get: (id: number) => get<Camera>(`/api/cameras/${id}`),
    create: (body: CameraInput) => post<Camera>("/api/cameras", body),
    update: (id: number, body: Partial<CameraInput>) => put<Camera>(`/api/cameras/${id}`, body),
    remove: (id: number) => del<void>(`/api/cameras/${id}`),
    devices: () => get<{ usb: { index: number; width: number; height: number; fps: number; backend?: string; in_use?: string }[] }>("/api/cameras/devices"),
    testConnection: (body: { source_type: string; source_uri: string }) => post<Record<string, unknown> & { ok: boolean; message: string }>("/api/cameras/test-connection", body),
    frameInfo: (id: number) => get<{ width: number; height: number; source_width: number; source_height: number; fps: number; duration_s: number | null; frame_count: number | null; is_live: boolean }>(`/api/cameras/${id}/frame-info`),
    snapshotUrl: (id: number, t = 0) => `/api/cameras/${id}/snapshot?t=${t}&_=${Date.now()}`,
    previewUrl: (id: number) => `/api/cameras/${id}/preview.mjpg`,
    previewStatus: (id: number) => get<Record<string, unknown>>(`/api/cameras/${id}/preview/status`),
    scenes: (id: number) => get<Scene[]>(`/api/cameras/${id}/scenes`),
    latestScene: (id: number) => get<Scene>(`/api/cameras/${id}/scenes/latest`),
    saveScene: (id: number, body: { name?: string; document: SceneDocument; new_version?: boolean }) => post<Scene>(`/api/cameras/${id}/scenes`, body),
  },
  scenes: {
    get: (id: number) => get<Scene>(`/api/scenes/${id}`),
    validate: (document: SceneDocument) => post<{ ok: boolean; warnings: string[] }>("/api/scenes/validate", document),
  },
  videos: {
    list: () => get<Video[]>("/api/videos"),
    upload: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return post<Video>("/api/videos", fd);
    },
    register: (path: string) => post<Video>(`/api/videos/register${qs({ path })}`),
    remove: (id: number) => del<void>(`/api/videos/${id}`),
    fileUrl: (id: number) => `/api/videos/${id}/file`,
  },
  experiments: {
    list: (params: { project_id?: number; camera_id?: number } = {}) => get<Experiment[]>(`/api/experiments${qs(params)}`),
    get: (id: number) => get<Experiment>(`/api/experiments/${id}`),
    create: (body: ExperimentInput) => post<Experiment>("/api/experiments", body),
    update: (id: number, body: Partial<ExperimentInput> & { status?: string }) => put<Experiment>(`/api/experiments/${id}`, body),
    remove: (id: number) => del<void>(`/api/experiments/${id}`),
    duplicate: (id: number, name?: string) => post<Experiment>(`/api/experiments/${id}/duplicate${qs({ name })}`),
    runs: (id: number) => get<Run[]>(`/api/experiments/${id}/runs`),
    start: (id: number, body: { scene_config_id?: number | null; realtime?: boolean | null; loop?: boolean } = {}) => post<Run>(`/api/experiments/${id}/start`, body),
  },
  runs: {
    list: (params: { experiment_id?: number; camera_id?: number; active?: boolean; limit?: number } = {}) => get<Run[]>(`/api/runs${qs(params)}`),
    get: (id: number) => get<Run>(`/api/runs/${id}`),
    status: (id: number) => get<{ run_id: number; status: string; live: Record<string, unknown> | null; finished: boolean; recent_events: Record<string, unknown>[] }>(`/api/runs/${id}/status`),
    stop: (id: number) => post<{ ok: boolean; status?: string }>(`/api/runs/${id}/stop`),
    pause: (id: number) => post<{ ok: boolean }>(`/api/runs/${id}/pause`),
    resume: (id: number) => post<{ ok: boolean }>(`/api/runs/${id}/resume`),
    remove: (id: number) => del<void>(`/api/runs/${id}`),
    wsUrl: (id: number) => {
      const t = recognitionToken();
      return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/runs/${id}${t ? `?rtoken=${encodeURIComponent(t)}` : ""}`;
    },
  },
  recordings: {
    forRun: (runId: number) => get<Recording[]>(`/api/runs/${runId}/recordings`),
    list: (params: { experiment_id?: number; camera_id?: number; limit?: number } = {}) => get<Recording[]>(`/api/recordings${qs(params)}`),
    remove: (id: number) => del<void>(`/api/recordings/${id}`),
    removeForRun: (runId: number) => del<void>(`/api/runs/${runId}/recordings`),
    fileUrl: (id: number, download = false) => `/api/recordings/${id}/file${download ? "?download=true" : ""}`,
  },
  anomalies: {
    list: (params: { run_id?: number; experiment_id?: number; camera_id?: number; status?: string; kind?: string; feedback?: string; limit?: number; offset?: number } = {}) =>
      get<{ items: AnomalyRecord[]; total: number }>(`/api/anomalies${qs(params)}`),
    get: (id: number) => get<AnomalyRecord>(`/api/anomalies/${id}`),
    feedback: (id: number, body: { feedback: "true_positive" | "false_alarm" | null; note?: string; rebaseline?: boolean }) => post<AnomalyRecord & { rebaselined: boolean }>(`/api/anomalies/${id}/feedback`, body),
    describe: (id: number) => post<AnomalyRecord>(`/api/anomalies/${id}/describe`),
    raise: (id: number) => post<AnomalyRecord>(`/api/anomalies/${id}/raise`),
    remove: (id: number) => del<void>(`/api/anomalies/${id}`),
    rebaseline: (runId: number, zoneId: string | null = null) => post<{ sent: boolean }>(`/api/runs/${runId}/anomaly/rebaseline`, { zone_id: zoneId }),
  },
  anomalyAssistant: {
    get: () => get<AnomalyAssistantView>("/api/anomaly/assistant"),
    save: (body: LLMSettings & { api_key?: string | null }) => put<AnomalyAssistantView>("/api/anomaly/assistant", body),
    test: () => post<AnomalyTestResult>("/api/anomaly/assistant/test"),
    models: () => get<{ models: string[] }>("/api/anomaly/assistant/models"),
  },
  localModels: {
    status: () => get<LocalSetupStatus>("/api/anomaly/local"),
    install: () => post<LocalJob>("/api/anomaly/local/install"),
    start: () => post<{ started: boolean; message: string }>("/api/anomaly/local/start"),
    pull: (model: string) => post<LocalJob>("/api/anomaly/local/pull", { model }),
    remove: (model: string) => post<{ deleted: string }>("/api/anomaly/local/delete", { model }),
    unload: (model: string) => post<{ unloaded: string }>("/api/anomaly/local/unload", { model }),
    use: (model: string) => post<AnomalyAssistantView>("/api/anomaly/local/use", { model }),
  },
  events: {
    list: (params: Record<string, unknown>) => get<Page<EventRecord>>(`/api/events${qs(params)}`),
    facets: (params: Record<string, unknown>) => get<Record<string, { value: string; count: number }[]>>(`/api/events/facets${qs(params)}`),
    exportUrl: (params: Record<string, unknown>) => `/api/events/export${qs(params)}`,
    timeline: (runId: number) =>
      get<{ run_id: number; markers: { id: number; t: number; type: string; route: string | null; object: string | null; track_id: number; cls: string; entity?: Record<string, unknown> }[] }>(`/api/events/runs/${runId}/timeline`),
  },
  analytics: {
    run: (id: number) => get<Record<string, any>>(`/api/analytics/runs/${id}/summary`),
    runSeries: (id: number, bucket = 60, eventType?: string) => get<{ series: { start_s: number; counts: Record<string, number>; total: number }[] }>(`/api/analytics/runs/${id}/series${qs({ bucket_s: bucket, event_type: eventType })}`),
    tracks: (id: number) => get<TrackSummary[]>(`/api/analytics/runs/${id}/tracks`),
    trajectories: (id: number) => get<{ trajectories: { track_id: number; object_class: string; points: number[][] }[] }>(`/api/analytics/runs/${id}/trajectories`),
    heatmap: (id: number, grid = 48) => get<{ grid: number; cells: number[][]; samples: number }>(`/api/analytics/runs/${id}/heatmap?grid=${grid}`),
    experiment: (id: number) => get<Record<string, any>>(`/api/analytics/experiments/${id}/summary`),
    compare: (ids: number[]) => get<{ experiments: Record<string, any>[] }>(`/api/analytics/compare?experiment_ids=${ids.join(",")}`),
    dashboard: () => get<Record<string, any>>("/api/analytics/dashboard"),
  },
  evaluations: {
    list: (runId: number) => get<Evaluation[]>(`/api/evaluations?run_id=${runId}`),
    create: (body: { run_id: number; event_id?: number | null; track_id?: number | null; verdict: string; expected?: string | null; note?: string }) => post<Evaluation>("/api/evaluations", body),
    remove: (id: number) => del<void>(`/api/evaluations/${id}`),
    metrics: (runId: number) => get<Record<string, any>>(`/api/evaluations/metrics?run_id=${runId}`),
    groundTruth: (runId: number) => get<{ id: number; object_id: string; label: string; count: number; note: string }[]>(`/api/evaluations/ground-truth?run_id=${runId}`),
    setGroundTruth: (body: { run_id: number; object_id: string; label?: string; count: number; note?: string }) => post<Record<string, unknown>>("/api/evaluations/ground-truth", body),
  },
  // Licensed recognition modules. Every call except status needs the recognition token.
  recognition: {
    status: () => get<RecognitionStatus>("/api/recognition/status"),
    me: () => get<Principal>("/api/recognition/access/me"),
    bootstrap: (name: string) => post<{ token: string; id: string; name: string; role: string }>("/api/recognition/access/bootstrap", { name }),
    tokens: () => get<AccessToken[]>("/api/recognition/access/tokens"),
    createToken: (body: { name: string; role: string; expires_in_days?: number | null }) => post<{ token: string; id: string; name: string; role: string }>("/api/recognition/access/tokens", body),
    revokeToken: (id: string) => del<{ revoked: boolean }>(`/api/recognition/access/tokens/${id}`),
    installLicense: (license: string) => post<{ verdict: LicenseSummary; status: RecognitionStatus }>("/api/recognition/license", { license }),
    removeLicense: () => del<{ removed: boolean; status: RecognitionStatus }>("/api/recognition/license"),
    addTrustedKey: (public_key: string, name: string) => post<{ path: string; trusted_issuers: number }>("/api/recognition/license/trusted-keys", { public_key, name }),
    settings: () => get<RecognitionSettingsResponse>("/api/recognition/settings"),
    updateSettings: (values: Record<string, unknown>) => put<{ values: Record<string, unknown>; changed: string[]; modules: RecognitionSettingsResponse["modules"] }>("/api/recognition/settings", { values }),
    people: () => get<RecognitionPerson[]>("/api/recognition/people"),
    person: (id: string) => get<RecognitionPerson>(`/api/recognition/people/${id}`),
    createPerson: (body: PersonInput) => post<RecognitionPerson>("/api/recognition/people", body),
    updatePerson: (id: string, body: Partial<PersonInput> & { clear_validity?: boolean }) => put<RecognitionPerson>(`/api/recognition/people/${id}`, body),
    disablePerson: (id: string) => post<RecognitionPerson>(`/api/recognition/people/${id}/disable`),
    enablePerson: (id: string) => post<RecognitionPerson>(`/api/recognition/people/${id}/enable`),
    deletePerson: (id: string) => del<{ deleted: boolean; templates_deleted: number; images: number; media: string }>(`/api/recognition/people/${id}`),
    reenroll: (id: string) => post<RecognitionPerson>(`/api/recognition/people/${id}/reenroll`),
    deleteLook: (id: string, look: string) => del<RecognitionPerson>(`/api/recognition/people/${id}/enrollment/looks/${encodeURIComponent(look)}`),
    analyzeImage: (id: string, file: Blob, view: string, look = "") => {
      const fd = new FormData();
      fd.append("file", file, "enrollment.jpg");
      fd.append("view", view);
      fd.append("variant", look);
      return post<EnrollmentAnalysis>(`/api/recognition/people/${id}/enrollment/analyze`, fd);
    },
    addImage: (id: string, file: Blob, view: string, look = "") => {
      const fd = new FormData();
      fd.append("file", file, "enrollment.jpg");
      fd.append("view", view);
      fd.append("variant", look);
      return post<{ analysis: EnrollmentAnalysis; image_id: string | null; template_id: string | null; person: RecognitionPerson }>(`/api/recognition/people/${id}/enrollment/images`, fd);
    },
    capture: (id: string, body: { camera_id: number; view: string; store: boolean; t?: number; variant?: string }) => post<{ analysis: EnrollmentAnalysis; stored: boolean; image_id?: string | null; person?: RecognitionPerson }>(`/api/recognition/people/${id}/enrollment/capture`, body),
    imageUrl: (personId: string, imageId: string) => `/api/recognition/people/${personId}/enrollment/images/${imageId}/file?rtoken=${encodeURIComponent(recognitionToken() ?? "")}`,
    deleteImage: (personId: string, imageId: string) => del<RecognitionPerson>(`/api/recognition/people/${personId}/enrollment/images/${imageId}`),
    finalize: (id: string) => post<{ result: EnrollmentResult; person: RecognitionPerson }>(`/api/recognition/people/${id}/enrollment/finalize`),
    vehicles: () => get<RecognitionVehicle[]>("/api/recognition/vehicles"),
    vehicleGroups: () => get<string[]>("/api/recognition/vehicles/groups"),
    createVehicle: (body: VehicleInput) => post<RecognitionVehicle>("/api/recognition/vehicles", body),
    updateVehicle: (id: string, body: Partial<VehicleInput>) => put<RecognitionVehicle>(`/api/recognition/vehicles/${id}`, body),
    deleteVehicle: (id: string) => del<{ deleted: boolean }>(`/api/recognition/vehicles/${id}`),
    parsePlate: (text: string, formats?: string) => post<ParsedPlate>("/api/recognition/plates/parse", { text, formats: formats || null }),
    events: (params: Record<string, unknown>) => get<Page<RecognitionEvent>>(`/api/recognition/events${qs(params)}`),
    event: (id: number) => get<RecognitionEvent>(`/api/recognition/events/${id}`),
    eventCropUrl: (id: number) => `/api/recognition/events/${id}/crop?rtoken=${encodeURIComponent(recognitionToken() ?? "")}`,
    deleteEvent: (id: number) => del<{ deleted: number }>(`/api/recognition/events/${id}`),
    deleteEvents: (body: { ids?: number[]; run_id?: number; person_id?: string; vehicle_id?: string; module?: string }) => post<{ deleted: number }>("/api/recognition/events/delete", body),
    exportUrl: (params: Record<string, unknown>) => `/api/recognition/events/export${qs({ ...params, rtoken: recognitionToken() ?? "" })}`,
    // Names for the opaque ids in ordinary events; needs a recognition token.
    resolve: (body: { identity_ids?: string[]; vehicle_ids?: string[] }) => post<ResolvedNames>("/api/recognition/resolve", body),
    liveTracks: (runId: number) => get<{ run_id: number; camera_id: number; seq: number; active: boolean; tracks: LiveEntity[] }>(`/api/recognition/live/${runId}/tracks`),
    identifyFile: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return post<IdentifyResult>("/api/recognition/test/identify", fd);
    },
    identifyCamera: (camera_id: number, t = 0) => post<IdentifyResult>("/api/recognition/test/identify/camera", { camera_id, t }),
    enrollmentCheck: () => get<EnrollmentCheck>("/api/recognition/test/enrollment"),
    // The operator's answers at the test bench: a verdict is only recorded,
    // teaching adds the picture to that person's enrollment.
    testFeedback: (body: { verdict: "correct" | "wrong" | "unknown_person"; person_id?: string | null; similarity?: number | null; corrected_person_id?: string | null; source?: "live" | "picture"; note?: string }) =>
      post<FeedbackSummary>("/api/recognition/test/feedback", body),
    testFeedbackLog: (limit = 50) => get<FeedbackSummary & { recent: { id: number; at: string; action: string; actor: string; target_id: string | null; detail: Record<string, unknown> }[] }>(`/api/recognition/test/feedback?limit=${limit}`),
    teach: (personId: string, file: Blob, look = "", force = false) => {
      const fd = new FormData();
      fd.append("file", file, "confirmed.jpg");
      fd.append("person_id", personId);
      if (look) fd.append("look", look);
      fd.append("force", String(force));
      return post<TeachResult>("/api/recognition/test/teach", fd);
    },
    activeRuns: () => get<{ run_id: number; camera_id: number; experiment_id: number; state: string; modules: string[]; has_diagnostics: boolean }[]>("/api/recognition/diagnostics/active"),
    diagnostics: (runId: number) => get<RunDiagnostics>(`/api/recognition/diagnostics/runs/${runId}`),
    audit: (limit = 200) => get<AuditRow[]>(`/api/recognition/audit?limit=${limit}`),
    benchmark: (module: "face" | "plate", device = "auto") => post<Record<string, unknown>>("/api/recognition/benchmark", { module, device }),
  },
};
