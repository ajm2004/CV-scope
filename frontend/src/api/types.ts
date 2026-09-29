import type { RelationExperimentSettings } from "../relationships/api";

export type { RelationExperimentSettings };

// Types mirroring the backend API schemas.

export interface Project {
  id: number;
  name: string;
  description: string;
  tags: string[];
  created_at: string;
  updated_at: string;
  camera_count: number;
  experiment_count: number;
  site_count: number;
}

export interface Site {
  id: number;
  project_id: number;
  name: string;
  description: string;
  created_at: string;
}

export interface Video {
  id: number;
  filename: string;
  path: string;
  size_bytes: number;
  duration_s: number | null;
  fps: number | null;
  width: number | null;
  height: number | null;
  frame_count: number | null;
  created_at: string;
}

export type SourceType = "file" | "usb" | "rtsp" | "http";

export interface Camera {
  id: number;
  project_id: number;
  site_id: number | null;
  name: string;
  location: string;
  source_type: SourceType;
  source_uri: string;
  video_id: number | null;
  width: number | null;
  height: number | null;
  requested_fps: number | null;
  processing_fps: number | null;
  rotation: number;
  crop: Record<string, number> | null;
  inference_size: number | null;
  reconnect: Record<string, unknown>;
  enabled: boolean;
  notes: string;
  /** Video files: when the recording started (ISO, UTC); runs date results by it. */
  recorded_at: string | null;
  created_at: string;
  updated_at: string;
  video: Video | null;
  latest_scene_id: number | null;
  latest_scene_version: number | null;
  active_run_id: number | null;
}

export interface CameraInput {
  project_id: number;
  site_id?: number | null;
  name: string;
  location?: string;
  source_type: SourceType;
  source_uri?: string;
  video_id?: number | null;
  width?: number | null;
  height?: number | null;
  requested_fps?: number | null;
  processing_fps?: number | null;
  rotation?: number;
  crop?: Record<string, number> | null;
  inference_size?: number | null;
  reconnect?: Record<string, unknown>;
  enabled?: boolean;
  notes?: string;
  recorded_at?: string | null;
}

export interface Point {
  x: number;
  y: number;
}

export type Direction = "both" | "forward" | "reverse";
export type LineType = "line" | "gate";
export type ZoneType = "zone" | "checkpoint" | "ignore";
export type ZoneMeasure = "entry" | "exit" | "occupancy" | "dwell";

interface SceneObjectBase {
  id: string;
  name: string;
  enabled: boolean;
  locked: boolean;
  visible: boolean;
  color: string | null;
  notes: string;
  classes: string[];
}

export interface LineObject extends SceneObjectBase {
  type: LineType;
  points: [Point, Point];
  direction: Direction;
  actions: ("count" | "record")[];
  min_confidence: number;
  min_track_age: number;
  debounce_s: number;
  /** The camera cannot see past the line: objects that disappear or appear at it count as crossing. */
  doorway?: boolean;
}

export interface ZoneObject extends SceneObjectBase {
  type: ZoneType;
  points: Point[];
  measures: ZoneMeasure[];
  min_dwell_s: number;
  max_dwell_s: number | null;
  max_objects: number | null;
  min_confidence: number;
  min_track_age: number;
  debounce_s: number;
}

export type SceneObject = LineObject | ZoneObject;

export interface RouteDefinition {
  id: string;
  name: string;
  enabled: boolean;
  color: string | null;
  start: string;
  sequence: string[];
  end: string;
  classes: string[];
  timeout_s: number;
  strict_sequence: boolean;
}

export interface CalibrationPoint {
  image: Point;
  ground_x: number;
  ground_y: number;
}

export interface Calibration {
  unit: string;
  points: CalibrationPoint[];
  known_distance: { a: Point; b: Point; distance: number } | null;
  notes: string;
}

export interface SceneDocument {
  version: number;
  frame_width: number;
  frame_height: number;
  objects: SceneObject[];
  routes: RouteDefinition[];
  calibration: Calibration | null;
}

export interface Scene {
  id: number;
  camera_id: number;
  version: number;
  name: string;
  document: SceneDocument;
  frozen: boolean;
  created_from_id: number | null;
  created_at: string;
}

export type InteractionKind = "crosses" | "enters" | "exits";

export interface RuleTrigger {
  kind: InteractionKind;
  object_id: string;
  direction: Direction;
}

export interface RuleStep extends RuleTrigger {
  within_s: number | null;
}

export interface RuleAction {
  kind: "count" | "record_event" | "webhook" | "log";
  label?: string | null;
  url?: string | null;
}

/** Recognition condition of a rule (licensed modules): who or which vehicle. */
export type SubjectMode = "any" | "anonymous" | "recognized" | "registered" | "specific";

export interface RuleSubject {
  mode: SubjectMode;
  identity_ids: string[];
  plates: string[];
  vehicle_ids: string[];
  groups: string[];
}

export const ANY_SUBJECT: RuleSubject = { mode: "any", identity_ids: [], plates: [], vehicle_ids: [], groups: [] };

export interface RuleRelation {
  relation: string;
  direction: "any" | "outgoing" | "incoming";
  other_classes: string[];
  other: RuleSubject;
  other_places: string[];
  min_state: "possible" | "likely" | "confirmed";
  recent_s: number | null;
}

export interface Rule {
  id: string;
  name: string;
  enabled: boolean;
  classes: string[];
  subject?: RuleSubject;
  /** HAS RELATIONSHIP clause (relationship engine) */
  relation?: RuleRelation | null;
  trigger: RuleTrigger;
  then: RuleStep[];
  remains_for_s: number | null;
  record_as: string;
  actions: RuleAction[];
  timeout_s: number | null;
}

export interface InferenceSettings {
  preset: "auto" | "fast" | "balanced" | "accurate" | "custom";
  provider: string;
  device: string;
  image_size: number | null;
  confidence: number;
  iou: number;
  half: boolean | null;
  processing_fps: number | null;
  frame_skip: number;
  realtime: boolean;
}

export interface Run {
  id: number;
  experiment_id: number;
  camera_id: number | null;
  scene_config_id: number | null;
  status: string;
  started_at: string | null;
  ended_at: string | null;
  error: string | null;
  snapshot: Record<string, unknown>;
  stats: Record<string, unknown>;
  created_at: string;
  live: LiveStatus | null;
}

export interface Counter {
  key: string;
  label: string;
  group: string;
  kind: string;
  value: number;
}

export interface LiveStatus {
  state: string;
  frame_index: number;
  media_time_s: number;
  processed_frames: number;
  read_frames: number;
  pipeline_fps: number;
  source_fps: number;
  timings_ms: Record<string, number>;
  counters: Counter[];
  tracker: Record<string, number>;
  rule_stats: Record<string, number>;
  active_tracks: number;
  routes_in_progress: number;
  zone_occupancy: Record<string, number>;
  detector: Record<string, unknown>;
  source: Record<string, unknown>;
  error: string | null;
  progress: number | null;
  wall_time: number;
  reconnects: number;
}

export interface Experiment {
  id: number;
  project_id: number;
  camera_id: number | null;
  scene_config_id: number | null;
  name: string;
  description: string;
  notes: string;
  condition_notes: string;
  tags: string[];
  object_classes: string[];
  model_id: string;
  tracker_id: string;
  inference: InferenceSettings;
  tracker_settings: Record<string, unknown>;
  rules: Rule[];
  recording: RecordingSettings;
  anomaly: AnomalySettings;
  relations?: RelationExperimentSettings;
  status: string;
  created_at: string;
  updated_at: string;
  run_count: number;
  last_run: Run | null;
  camera_name: string | null;
}

export interface ExperimentInput {
  project_id: number;
  camera_id?: number | null;
  scene_config_id?: number | null;
  name: string;
  description?: string;
  notes?: string;
  condition_notes?: string;
  tags?: string[];
  object_classes?: string[];
  model_id?: string;
  tracker_id?: string;
  inference?: Partial<InferenceSettings>;
  tracker_settings?: Record<string, unknown>;
  rules?: Rule[];
  recording?: RecordingSettings;
  anomaly?: AnomalySettings;
  relations?: RelationExperimentSettings;
}

/** Video recording of live runs, set per experiment. */
export interface RecordingSettings {
  /** presence = from the entry of an object to its exit, dwell included. */
  mode: "off" | "continuous" | "events" | "presence";
  pre_s: number;
  post_s: number;
  event_types: string[];
  presence_grace_s: number;
  overlay: boolean;
  fps: number;
  segment_minutes: number;
  max_clip_s: number;
}

/** A video file recorded during a run: the whole run in segments, or a clip around events. */
export interface Recording {
  id: number;
  run_id: number;
  experiment_id: number | null;
  camera_id: number | null;
  kind: "continuous" | "event" | "presence";
  mime: string;
  codec: string;
  width: number;
  height: number;
  fps: number;
  frames: number;
  media_start_s: number;
  media_end_s: number;
  duration_s: number;
  started_at: string;
  ended_at: string;
  size_bytes: number;
  overlay: boolean;
  triggers: { type: string; label: string; track_id: number; media_time_s: number }[];
  trigger_count: number;
  playable: boolean;
  url: string;
}

export interface EventRecord {
  id: number;
  run_id: number;
  experiment_id: number;
  camera_id: number | null;
  track_id: number;
  object_class: string;
  event_type: string;
  rule_id: string | null;
  rule_name: string | null;
  route: string | null;
  object_id: string | null;
  object_name: string | null;
  direction: string | null;
  frame_index: number;
  media_time_s: number;
  wall_time: string;
  entered_at_s: number | null;
  completed_at_s: number | null;
  duration_s: number | null;
  avg_speed: number | null;
  speed_unit: string | null;
  confidence: number | null;
  context: Record<string, unknown>;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface TrackSummary {
  id: number;
  run_id: number;
  track_id: number;
  object_class: string;
  first_seen_s: number;
  last_seen_s: number;
  n_frames: number;
  path_length: number | null;
  path_unit: string;
  avg_speed: number | null;
  speed_unit: string | null;
  mean_confidence: number | null;
  final_state: string;
  route_result: string | null;
  lost_count: number;
}

export interface GpuInfo {
  index: number;
  name: string;
  vendor: string;
  vram_total_bytes: number | null;
  vram_used_bytes: number | null;
  driver_version: string | null;
  cuda_driver_version: string | null;
  compute_capability: string | null;
  utilization_percent: number | null;
  integrated: boolean;
  source: string;
}

export interface HardwareReport {
  probed_at: number;
  os: string;
  os_version: string;
  python_version: string;
  hostname: string;
  cpu: {
    model: string;
    architecture: string;
    physical_cores: number | null;
    logical_cores: number | null;
    max_frequency_mhz: number | null;
    current_usage_percent: number | null;
    flags: string[];
  };
  memory: { total_bytes: number; available_bytes: number; used_percent: number };
  disk: { path: string; total_bytes: number; free_bytes: number };
  gpus: GpuInfo[];
  acceleration: {
    cuda_available: boolean;
    cuda_version: string | null;
    cudnn_version: string | null;
    rocm_available: boolean;
    rocm_version: string | null;
    mps_available: boolean;
    tensorrt_available: boolean;
    openvino_available: boolean;
    onnxruntime_providers: string[];
  };
  runtimes: { id: string; label: string; available: boolean; provider: string; device: string; version: string | null; detail: string }[];
  providers: Record<string, boolean>;
  library_versions: Record<string, string | null>;
}

export interface ModelRecommendation {
  tier: string;
  title: string;
  model_id: string;
  model_name: string;
  provider: string;
  device: string;
  image_size: number;
  reasons: string[];
  estimated: boolean;
  installed: boolean;
  available: boolean;
  unavailable_reason: string;
}

export interface RecognitionImpact {
  modules: Record<string, { stack: string; units_per_frame: number; device: string }>;
  components: string[];
  detector_model_id: string | null;
  processing_fps: number;
  camera_capacity_without: number;
  camera_capacity_with: number;
  reduction_percent: number;
  warning: string | null;
  basis: string;
  note: string;
}

export interface RecommendationSet {
  workload_class: string;
  workload_summary: string;
  default_tier: string;
  runtime_id: string;
  runtime_label: string;
  runtime_reason: string;
  fallback_chain: string[];
  tiers: ModelRecommendation[];
  warnings: string[];
  benchmarked: boolean;
  recognition?: RecognitionImpact | null;
}

export interface InstallJob {
  id: string;
  model_id: string;
  status: string;
  progress: number;
  message: string;
  error: string | null;
  path: string | null;
}

export interface ModelInfo {
  id: string;
  name: string;
  family: string;
  provider: string;
  task: string;
  classes: string[];
  trackable_classes: string[];
  file_name: string;
  download_url: string | null;
  size_mb: number | null;
  parameters_m: number | null;
  min_vram_gb: number | null;
  min_ram_gb: number;
  compute_class: string;
  cpu_suitability: string;
  gpu_suitability: string;
  relative_accuracy: number;
  relative_speed: number;
  reference_map: number | null;
  reference_note: string;
  runtimes: string[];
  default_image_size: number;
  license: string;
  license_note: string;
  source_url: string;
  requires_package: string;
  export_from: string | null;
  notes: string;
  subdir?: string;
  archive_member?: string | null;
  extra_files?: { url: string; file_name: string }[];
  module?: "face" | "plate" | null;
  model_version?: string;
  meta?: Record<string, unknown>;
  installed: boolean;
  installed_size_bytes: number | null;
  provider_available: boolean;
  path: string | null;
  export_source_installed?: boolean;
  job: InstallJob | null;
  recommended_tier: string | null;
  benchmark: { device: string; results: Record<string, unknown>; created_at: string } | null;
}

export interface TrackerSettingOption {
  value: string;
  label: string;
  available?: boolean;
  reason?: string;
}

export interface TrackerSetting {
  key: string;
  label: string;
  type: "float" | "int" | "enum" | "bool";
  default: number | string | boolean | null;
  min?: number;
  max?: number;
  nullable?: boolean;
  help?: string;
  options?: TrackerSettingOption[];
}

export interface TrackerInfo {
  id: string;
  name: string;
  description: string;
  license: string;
  source: string;
  available: boolean;
  unavailable_reason?: string;
  settings: TrackerSetting[];
}

export interface SystemStatus {
  version: string;
  setup_completed: boolean;
  database: { url: string; ok: boolean; error: string | null; dialect: string };
  data_dir: string;
  models_dir: string;
  counts: Record<string, number>;
  active_runs: { run_id: number; state: string; camera_id: number }[];
  time: number;
}

export interface Evaluation {
  id: number;
  run_id: number;
  event_id: number | null;
  track_id: number | null;
  verdict: string;
  expected: string | null;
  note: string;
  created_at: string;
}

export interface SettingDefinition {
  key: string;
  section: string;
  label: string;
  kind: string;
  options?: string[];
  help?: string;
  advanced: boolean;
}

// ----------------------------------------------------------------- licensed recognition modules
export type ModuleStateId = "not_licensed" | "licensed" | "expired" | "disabled";

export interface ModuleState {
  module: "face" | "plate";
  state: ModuleStateId;
  reason: string;
  licensed: boolean;
  active: boolean;
  label: string;
  models_ready: boolean;
}

export interface LicenseSummary {
  state: string;
  reason: string;
  issuer_key: string | null;
  license_id?: string;
  licensee?: string;
  issuer?: string;
  issued_at?: string;
  expires_at?: string | null;
  days_left?: number | null;
  modules?: string[];
  max_cameras?: number | null;
  hardware_bound?: boolean;
  notes?: string;
}

export interface RecognitionStatus {
  modules: { face: ModuleState; plate: ModuleState };
  license: { license: LicenseSummary; license_installed: boolean; trusted_issuers: number; hardware_id: string; license_path: string };
  access: { has_tokens: boolean };
  missing_models: string[];
  face_stack: string;
  any_licensed: boolean;
}

export type RecognitionRole = "viewer" | "operator" | "admin";

export interface Principal {
  token_id: string;
  name: string;
  role: RecognitionRole;
}

export interface AccessToken {
  id: string;
  name: string;
  role: RecognitionRole;
  active: boolean;
  created_by: string;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
}

export interface RecognitionSettingDefinition extends SettingDefinition {
  default: unknown;
  min?: number;
  max?: number;
  nullable?: boolean;
}

export interface PlateFormatInfo {
  id: string;
  name: string;
  country: string;
  pattern: string;
  region: string | null;
  description: string;
  builtin: boolean;
}

export interface RecognitionSettingsResponse {
  values: Record<string, unknown>;
  definitions: RecognitionSettingDefinition[];
  face_stacks: Record<string, string>;
  plate_formats: PlateFormatInfo[];
  modules: { face: ModuleState; plate: ModuleState };
}

export type EnrollmentView = "front" | "left" | "right" | "above" | "below" | "lighting" | "rear";

export interface QualityDetail {
  score: number;
  usable: boolean;
  size_px: number;
  blur: number;
  exposure: number;
  contrast: number;
  yaw: number | null;
  pitch: number | null;
  occlusion: number;
  reasons: string[];
}

export interface EnrollmentImage {
  id: string;
  view: EnrollmentView;
  /** The look this picture belongs to; "" is the first enrollment. */
  variant: string;
  biometric: boolean;
  width: number;
  height: number;
  quality: number | null;
  quality_detail: Partial<QualityDetail>;
  created_at: string | null;
}

export interface EnrollmentAnalysis {
  view: EnrollmentView;
  face_found: boolean;
  accepted: boolean;
  guidance: string[];
  box: number[] | null;
  quality: QualityDetail | null;
  width: number;
  height: number;
  model_version: string;
}

export interface EnrollmentLook {
  name: string;
  images: number;
  templates: number;
  views: string[];
  consistency: number | null;
  link_to_first: number | null;
  created_at: string | null;
}

/** What a track resolved to, for viewers holding a recognition token. */
export interface LiveEntity {
  track_id: number;
  object_class: string;
  state: string;
  kind: string;
  status: string | null;
  identity_id: string | null;
  display_name: string | null;
  plate: string | null;
  vehicle_id: string | null;
  vehicle_label: string | null;
  groups: string[];
  confidence: number | null;
}

export interface ResolvedNames {
  identities: Record<string, { id: string; display_name: string; reference_id: string | null; active: boolean; enrollment_status: string }>;
  vehicles: Record<string, { id: string; plate: string; label: string; groups: string[]; active: boolean }>;
  missing: string[];
}

export interface IdentifyCandidate {
  identity_id: string;
  display_name: string;
  similarity: number;
  over_match: boolean;
  over_possible: boolean;
}

export interface IdentifyFace {
  box: number[];
  detector_score: number;
  quality: QualityDetail;
  usable: boolean;
  status: "recognized" | "possible_match" | "unknown" | "insufficient_quality";
  best: { identity_id: string; display_name: string; similarity: number } | null;
  runner_up: number | null;
  candidates: IdentifyCandidate[];
  advice: string[];
}

export interface IdentifyResult {
  width: number;
  height: number;
  n_faces: number;
  faces: IdentifyFace[];
  model_version: string;
  identities: number;
  templates: number;
  identities_other_model: number;
  thresholds: { match: number; possible: number; margin: number; min_face_px: number; min_quality: number };
}

export interface EnrollmentCheckPerson {
  id: string;
  display_name: string;
  reference_id: string | null;
  active: boolean;
  enrollment_status: string;
  enrollment_quality: number | null;
  templates: number;
  templates_other_model: number;
  views: string[];
  looks: string[];
  n_looks: number;
  self_similarity: number | null;
  weakest_pair: number | null;
  model_version: string;
  nearest_other: { id: string; display_name: string; similarity: number } | null;
  advice: string[];
  verdict: "ok" | "weak" | "risk" | "blocked";
}

export interface FeedbackSummary {
  checked: number;
  correct: number;
  wrong: number;
  unknown_person: number;
  taught: number;
}

export interface TeachResult {
  person: RecognitionPerson;
  similarity: number | null;
  quality: QualityDetail | null;
  look: string;
  enrollment: EnrollmentResult;
}

export interface EnrollmentCheck {
  model_version: string;
  min_views: number;
  min_consistency: number;
  possible_threshold: number;
  people: EnrollmentCheckPerson[];
  counts: { total: number; ok: number; weak: number; risk: number; blocked: number };
}

export interface EnrollmentResult {
  status: "draft" | "enrolled" | "insufficient";
  quality: number | null;
  views: string[];
  templates: number;
  mean_quality: number;
  consistency: number | null;
  coverage: number;
  problems: string[];
  model_version: string;
  looks?: EnrollmentLook[];
  n_looks?: number;
}

export interface RecognitionPerson {
  id: string;
  display_name: string;
  reference_id: string | null;
  notes: string;
  active: boolean;
  valid_from: string | null;
  valid_until: string | null;
  enrollment_status: "draft" | "enrolled" | "insufficient";
  enrollment_quality: number | null;
  enrollment_summary: Partial<EnrollmentResult> & { finalized_at?: string };
  model_version: string;
  enrolled_at: string | null;
  n_templates: number;
  n_images: number;
  views: string[];
  /** Appearances this person was enrolled in; "" is the first enrollment. */
  looks: EnrollmentLook[];
  created_by: string;
  created_at: string | null;
  updated_at: string | null;
  images?: EnrollmentImage[];
}

export interface PersonInput {
  display_name: string;
  reference_id?: string | null;
  notes?: string;
  valid_from?: string | null;
  valid_until?: string | null;
}

export interface RecognitionVehicle {
  id: string;
  plate: string;
  country: string;
  region: string;
  vehicle_type: string;
  description: string;
  owner_ref: string;
  groups: string[];
  active: boolean;
  notes: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface VehicleInput {
  plate: string;
  country?: string;
  region?: string;
  vehicle_type?: string;
  description?: string;
  owner_ref?: string;
  groups?: string[];
  active?: boolean;
  notes?: string;
}

export interface ParsedPlate {
  raw: string;
  normalized: string;
  valid: boolean;
  format: string | null;
  format_name: string | null;
  country: string | null;
  region: string | null;
  fields: Record<string, string>;
  substitutions: number;
  exact?: ParsedPlate;
  formats_tried?: string[];
}

export interface RecognitionEvent {
  id: number;
  run_id: number | null;
  experiment_id: number | null;
  camera_id: number | null;
  track_id: number;
  object_class: string;
  module: "face" | "plate";
  kind: string;
  status: string;
  person_id: string | null;
  display_name: string | null;
  vehicle_id: string | null;
  vehicle_label: string | null;
  plate_raw: string | null;
  plate_normalized: string | null;
  plate_format: string | null;
  plate_region: string | null;
  plate_fields: Record<string, string>;
  similarity: number | null;
  second_similarity: number | null;
  confidence: number | null;
  quality: number | null;
  n_observations: number;
  usable_observations: number;
  best_frame_index: number | null;
  model_version: string;
  frame_index: number;
  media_time_s: number;
  wall_time: string | null;
  context: Record<string, unknown>;
  has_crop: boolean;
}

export interface AuditRow {
  id: number;
  at: string;
  actor: string;
  actor_role: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  detail: Record<string, unknown>;
  client: string | null;
}

export interface FaceTrackDiagnostics {
  track_id: number;
  face_detected: boolean;
  quality: Partial<QualityDetail> | null;
  observations: number;
  usable: number;
  kept: number;
  best_frame: number | null;
  best_quality: number | null;
  rejected: Record<string, number>;
  candidate: string | null;
  similarity: number | null;
  second_similarity: number | null;
  result: string;
  identity: string | null;
  identity_id: string | null;
  settled: boolean;
  revalidate_at: number | null;
  history: Record<string, unknown>[];
}

export interface PlateTrackDiagnostics {
  track_id: number;
  plate_detected: boolean;
  quality: Partial<QualityDetail> | null;
  raw_ocr: string | null;
  reads: number;
  usable: number;
  rejected: Record<string, number>;
  consensus: { text: string; confidence: number; n_observations: number; complete: boolean } | null;
  normalized: string | null;
  format: string | null;
  vehicle: string | null;
  vehicle_id: string | null;
  result: string;
  confidence: number | null;
  best_frame: number | null;
  settled: boolean;
  history: Record<string, unknown>[];
}

export interface RunDiagnostics {
  run_id: number;
  active: boolean;
  modules: string[];
  recognition: string[] | null;
  diagnostics: {
    face: { model: Record<string, unknown>; matcher: Record<string, unknown>; stats: Record<string, number>; tracks: FaceTrackDiagnostics[] } | null;
    plate: { model: Record<string, unknown>; parser: Record<string, unknown>; vehicles: number; stats: Record<string, number>; tracks: PlateTrackDiagnostics[] } | null;
    stats: Record<string, number>;
  } | null;
}

// ---------------------------------------------------------------------------- Anomaly Assistant
export type AnomalyKind = "presence" | "motion" | "appeared" | "disappeared" | "moved" | "changed";
export type AnomalyValidation = "deterministic" | "assisted" | "confirmed";

/** One watched area: a scene zone (by id) or the whole picture (id "frame"). */
export interface AnomalyZoneSettings {
  id: string;
  name: string;
  enabled: boolean;
  expected_state: string;
  sensitivity: "low" | "medium" | "high" | "custom";
  k_sigma: number | null;
  min_contrast: number | null;
  min_area_pct: number | null;
  persistence_s: number | null;
  min_confidence: number | null;
  detect: AnomalyKind[];
  presence_classes: string[];
  accept_after_s: number;
  cooldown_s: number;
  validation: AnomalyValidation;
  interpret_at: "confirm" | "end";
  webhooks: string[];
  record_clip: boolean;
}

export interface AnomalySettings {
  enabled: boolean;
  zones: AnomalyZoneSettings[];
  analysis_fps: number;
  learn_s: number;
  adapt_minutes: number;
  working_width: number;
  use_ignore_regions: boolean;
  lighting_events: boolean;
  tamper_events: boolean;
  recognition: boolean;
  on_llm_failure: "raise" | "hold";
}

/** An object the detector tracked in the anomalous area, with an alias and recognition ids (never a name). */
export interface AnomalySubject {
  alias: string;
  track_id: number;
  object_class: string;
  detector_confidence?: number | null;
  kind?: string;
  identity_id?: string;
  vehicle_id?: string;
  status?: string;
  confidence?: number;
}

export interface AnomalyRecord {
  id: number;
  uid: string;
  run_id: number;
  experiment_id: number | null;
  camera_id: number | null;
  camera_name: string | null;
  zone_id: string;
  zone_name: string;
  expected_state: string;
  kind: string;
  kind_label: string;
  /** raised | awaiting_model | dismissed | held */
  status: string;
  published: boolean;
  confidence: number;
  area_pct: number;
  bbox: number[];
  started_media_s: number;
  confirmed_media_s: number;
  ended_media_s: number | null;
  duration_s: number | null;
  started_at: string;
  confirmed_at: string;
  ended_at: string | null;
  end_reason: string | null;
  summary: string;
  objects: { track_id: number; object_class: string; confidence: number }[];
  subjects: AnomalySubject[];
  metrics: Record<string, unknown>;
  evidence: Record<string, string>;
  validation: AnomalyValidation;
  interpret_at: "confirm" | "end";
  llm: {
    status: string;
    verdict: string | null;
    category: string | null;
    description: string | null;
    confidence: number | null;
    evidence: string | null;
    provider: string | null;
    model: string | null;
    latency_ms: number | null;
    error: string | null;
    at: string | null;
  };
  feedback: "true_positive" | "false_alarm" | null;
  note: string;
  created_at: string;
}

export type LLMProviderId = "none" | "local" | "openai" | "anthropic" | "gemini" | "openrouter" | "deepseek" | "custom";

export interface LLMSettings {
  provider: LLMProviderId;
  model: string;
  base_url: string;
  timeout_s: number;
  max_output_tokens: number;
  send_images: boolean;
  image_max_px: number;
  include_crops: boolean;
  max_concurrent: number;
  max_calls_per_hour: number;
  queue_limit: number;
  extra_body: Record<string, unknown>;
  json_mode: boolean;
}

export interface LLMProviderInfo {
  id: LLMProviderId;
  name: string;
  protocol: string | null;
  base_url: string;
  default_model: string;
  models: string[];
  key_env: string[];
  needs_key: boolean;
  vision: boolean;
  local: boolean;
  note: string;
}

export interface AnomalyAssistantView {
  settings: LLMSettings;
  resolved: { model: string; base_url: string; vision: boolean; local: boolean };
  keys: Record<string, { set: boolean; source: string; hint: string }>;
  providers: LLMProviderInfo[];
  local_models: LocalModelInfo[];
  local_warning: string;
  queue: { pending: number; calls_last_hour: number; calls: number; failures: number; skipped_budget: number; skipped_queue: number; last_latency_ms: number | null; last_error: string | null };
}

export interface AnomalyTestResult {
  ok: boolean;
  result: { verdict: string; category: string; description: string; confidence: number; evidence: string; provider: string; model: string; latency_ms: number; images_sent: number };
  expected: string;
}

export interface LocalModelInfo {
  model: string;
  download_gb: number;
  tier: "light" | "capable" | "large";
  vram_gb: number;
  note: string;
}

export interface LocalJob {
  id: string;
  kind: "install" | "pull";
  target: string;
  status: "running" | "done" | "failed";
  message: string;
  completed: number;
  total: number;
  progress: number | null;
  error: string | null;
  started: number;
  ended: number | null;
}

export interface LocalSetupStatus {
  ollama: {
    platform: string;
    url: string;
    installed: boolean;
    executable: string | null;
    running: boolean;
    version: string | null;
    models: { name: string; size: number; modified_at: string; parameter_size: string | null; quantization: string | null; families: string[] | null }[];
    loaded: { name: string; size: number; size_vram: number; expires_at: string }[];
    can_install: boolean;
    install_command: string | null;
    models_folder: string;
  };
  catalog: LocalModelInfo[];
  jobs: LocalJob[];
}
