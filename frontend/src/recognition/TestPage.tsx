/* Recognition test bench.
 *
 * Three questions, all read-only and never stored:
 *   1. Live camera  — would the person in front of this camera be recognized?
 *   2. Picture      — what does the system make of this photograph?
 *   3. Enrollment   — which profiles are strong, which need more pictures?
 *
 * Every answer shows the numbers behind it: the face quality, the similarity
 * of every candidate and the thresholds in force, so a wrong answer can be
 * traced to the camera, the picture or the enrollment. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { EnrollmentCheckPerson, EnrollmentResult, IdentifyFace, IdentifyResult, RecognitionPerson } from "../api/types";
import { Empty, ErrorNotice, Field, Modal, Notice, Panel, Pill, Tabs } from "../components/ui";
import GuidedEnrollment from "./GuidedEnrollment";
import { num } from "../lib/format";
import { roleAtLeast } from "../lib/recognitionToken";
import { usePrincipal, useRecognitionStatus } from "./hooks";
import RecognitionGate from "./RecognitionGate";
import { useLiveTest } from "./useLiveTest";

const LIVE_SOURCES = new Set(["usb", "rtsp", "http"]);

const STATUS_LABEL: Record<string, string> = {
  recognized: "Recognized",
  possible_match: "Possible match",
  unknown: "Unknown",
  insufficient_quality: "Insufficient quality",
};

const VERDICT: Record<string, { label: string; tone: "ok" | "warn" | "err" | "accent" }> = {
  ok: { label: "Healthy", tone: "ok" },
  weak: { label: "Needs more", tone: "warn" },
  risk: { label: "Mix-up risk", tone: "err" },
  blocked: { label: "Not matched", tone: "err" },
};

/** Similarities always keep their decimals: "1.00", not "1". */
function sim(value: number, digits = 2): string {
  return value.toFixed(digits);
}

function statusTone(status: string): "ok" | "warn" | "err" | "" {
  if (status === "recognized") return "ok";
  if (status === "possible_match") return "warn";
  if (status === "insufficient_quality") return "err";
  return "";
}

function faceTitle(f: IdentifyFace): string {
  if (f.status === "recognized" && f.best) return f.best.display_name;
  if (f.status === "possible_match" && f.best) return `? ${f.best.display_name}`;
  return STATUS_LABEL[f.status] ?? f.status;
}

/** The picture with a box and a label over every face the detector found. */
function FaceStage({ src, result, mirror = false }: { src: string | null; result: IdentifyResult | null; mirror?: boolean }) {
  return (
    <div className={`face-stage ${mirror ? "mirror" : ""}`}>
      {src ? <img src={src} alt="Tested picture" /> : <div className="stage-msg">Waiting for the camera…</div>}
      {result &&
        result.width > 0 &&
        result.faces.map((f, i) => {
          const [x1, y1, x2, y2] = f.box;
          // The picture itself is mirrored for webcams, so the box is too.
          const left = mirror ? result.width - x2 : x1;
          const style = {
            left: `${(left / result.width) * 100}%`,
            top: `${(y1 / result.height) * 100}%`,
            width: `${((x2 - x1) / result.width) * 100}%`,
            height: `${((y2 - y1) / result.height) * 100}%`,
          };
          return (
            <div key={i} className={`face-box ${f.status}`} style={style}>
              <span className="face-tag">
                {faceTitle(f)}
                {f.best ? ` · ${f.best.similarity.toFixed(2)}` : ""}
              </span>
            </div>
          );
        })}
    </div>
  );
}

/** Candidates, quality and advice for one picture. */
function ResultDetail({ result }: { result: IdentifyResult }) {
  if (result.n_faces === 0)
    return (
      <Notice tone="warn">
        No face was found in this picture. For recognition a face must be at least {num(result.thresholds.min_face_px, 0)} px high, reasonably sharp and not turned too far away.
      </Notice>
    );
  return (
    <div className="stack" style={{ gap: 12 }}>
      {result.faces.map((f, i) => (
        <div key={i} className="stack" style={{ gap: 6 }}>
          <div className="row wrap">
            <Pill tone={statusTone(f.status)}>{STATUS_LABEL[f.status] ?? f.status}</Pill>
            {f.best && (
              <strong>
                {f.best.display_name} · {sim(f.best.similarity, 3)}
              </strong>
            )}
            <span className="small muted">
              face {num(f.quality.size_px, 0)} px · quality {num(f.quality.score, 2)} · sharpness {num(f.quality.blur, 2)} · exposure {num(f.quality.exposure, 2)}
              {f.quality.yaw !== null ? ` · yaw ${num(f.quality.yaw, 2)}` : ""}
              {f.runner_up != null ? ` · runner-up ${sim(f.runner_up)}` : ""}
            </span>
          </div>
          {f.candidates.length > 0 && (
            <table className="table">
              <thead>
                <tr>
                  <th>Enrolled person</th>
                  <th className="num">Similarity</th>
                  <th>Over the threshold</th>
                </tr>
              </thead>
              <tbody>
                {f.candidates.map((c) => (
                  <tr key={c.identity_id}>
                    <td>{c.display_name}</td>
                    <td className="num">{sim(c.similarity, 3)}</td>
                    <td>
                      {c.over_match ? <Pill tone="ok">Recognized</Pill> : c.over_possible ? <Pill tone="warn">Possible</Pill> : <span className="muted">below {sim(result.thresholds.possible)}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {f.advice.length > 0 && (
            <Notice tone={f.status === "recognized" ? undefined : "warn"}>
              {f.advice.map((a) => (
                <div key={a}>{a}</div>
              ))}
            </Notice>
          )}
        </div>
      ))}
    </div>
  );
}

function Thresholds({ result }: { result: Pick<IdentifyResult, "thresholds" | "identities" | "templates" | "model_version" | "identities_other_model"> }) {
  return (
    <div className="hint">
      {result.identities} enrolled {result.identities === 1 ? "person" : "people"} · {result.templates} templates · Recognized at {num(result.thresholds.match, 2)}, possible at {num(result.thresholds.possible, 2)}, margin {num(result.thresholds.margin, 2)}, smallest face {num(result.thresholds.min_face_px, 0)} px · models {result.model_version || "–"}
      {result.identities_other_model > 0 ? ` · ${result.identities_other_model} profile(s) enrolled with other models are ignored` : ""}
    </div>
  );
}

/** Create a profile and capture it, without leaving the test. */
function RegisterFromTest({ cameraId, onDone, onClose }: { cameraId: number; onDone: (p: RecognitionPerson) => void; onClose: () => void }) {
  const cameras = useQuery({ queryKey: ["cameras", "all"], queryFn: () => api.cameras.list() });
  const [name, setName] = useState("");
  const [reference, setReference] = useState("");
  const [person, setPerson] = useState<RecognitionPerson | null>(null);
  const [result, setResult] = useState<EnrollmentResult | null>(null);
  const create = useMutation({ mutationFn: () => api.recognition.createPerson({ display_name: name.trim(), reference_id: reference.trim() || null }), onSuccess: setPerson });
  const finalize = useMutation({
    mutationFn: () => api.recognition.finalize(person!.id),
    onSuccess: (r) => {
      setResult(r.result);
      setPerson(r.person);
    },
  });
  const thisCamera = (cameras.data ?? []).filter((c) => c.id === cameraId);
  return (
    <Modal
      title={person ? `Enrolling ${person.display_name}` : "Register this person"}
      onClose={onClose}
      width={900}
      footer={
        person ? (
          <div className="row">
            <button className="btn" onClick={() => finalize.mutate()} disabled={finalize.isPending || person.n_templates === 0}>
              Finish and check quality
            </button>
            <button className="btn primary" onClick={() => onDone(person)}>
              Back to the test
            </button>
          </div>
        ) : null
      }
    >
      <div className="stack">
        {!person ? (
          <>
            <Notice>
              Enrolling is deliberate: give the person a name they agreed to, then capture them. Nobody is identified who was not enrolled here.
            </Notice>
            <div className="form-grid">
              <Field label="Display name">
                <input autoFocus type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="Research Subject 002" onKeyDown={(e) => e.key === "Enter" && name.trim() && create.mutate()} />
              </Field>
              <Field label="Reference id (optional)">
                <input type="text" value={reference} onChange={(e) => setReference(e.target.value)} placeholder="E-002" />
              </Field>
            </div>
            {create.isError && <ErrorNotice error={create.error} />}
            <div className="row">
              <button className="btn primary" disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>
                Create and start the capture
              </button>
            </div>
          </>
        ) : (
          <>
            <GuidedEnrollment person={person} cameras={thisCamera} onChanged={setPerson} />
            {finalize.isError && <ErrorNotice error={finalize.error} />}
            {result && (
              <Notice tone={result.status === "enrolled" ? "ok" : "warn"}>
                {result.status === "enrolled" ? "Enrolled." : "Not enough yet."} Quality {num((result.quality ?? 0) * 100, 0)}% · views {result.views.join(", ") || "none"}
                {result.problems.map((p) => (
                  <div key={p}>{p}</div>
                ))}
              </Notice>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}

type Prompt = { kind: "confirm"; personId: string; name: string; similarity: number; status: string } | { kind: "register" };

const ASK_AGAIN_MS = 20_000; // do not ask about the same person more often than this
const STABLE_MS = 1200; // the same face has to be on screen this long before asking
const UNKNOWN_MS = 2500;

function LiveTest() {
  const cameras = useQuery({ queryKey: ["cameras", "all"], queryFn: () => api.cameras.list() });
  const people = useQuery({ queryKey: ["recognition-people"], queryFn: api.recognition.people });
  const live = useMemo(() => (cameras.data ?? []).filter((c) => LIVE_SOURCES.has(c.source_type)), [cameras.data]);
  const [cameraId, setCameraId] = useState<number | "">("");
  const [running, setRunning] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [correcting, setCorrecting] = useState(false);
  const [teachOnYes, setTeachOnYes] = useState(true);
  const [prompt, setPrompt] = useState<Prompt | null>(null);
  const [pending, setPending] = useState<string | null>(null); // person a confirmation was sent for
  const seen = useRef<{ id: string | null; since: number }>({ id: null, since: 0 });
  const answered = useRef<Record<string, number>>({});
  useEffect(() => {
    if (cameraId !== "" && live.some((c) => c.id === cameraId)) return;
    const stored = Number(localStorage.getItem("pathscope.enrollmentCamera") ?? "");
    const pick = live.find((c) => c.id === stored) ?? live[0];
    setCameraId(pick ? pick.id : "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live.map((c) => c.id).join(",")]);
  const qc = useQueryClient();
  const { ready, frameUrl, result, error, connected, counts, taught, refused, note, send, setTaught } = useLiveTest(
    running && !registering && cameraId !== "" ? Number(cameraId) : null,
    running && !registering,
    () => {
      qc.invalidateQueries({ queryKey: ["recognition-people"] });
      qc.invalidateQueries({ queryKey: ["recognition-enrollment-check"] });
    },
  );

  // Ask about the face on screen: the same person at most every 20 seconds.
  const face = result?.faces?.[0] ?? null;
  useEffect(() => {
    if (!running || registering) return;
    const now = Date.now();
    const id = face?.best?.identity_id ?? (face?.usable ? "__unknown__" : null);
    if (seen.current.id !== id) seen.current = { id, since: now };
    if (prompt || pending || !id || !face) return;
    const stable = now - seen.current.since;
    const last = answered.current[id] ?? 0;
    if (now - last < ASK_AGAIN_MS) return;
    if (id !== "__unknown__" && face.best && stable > STABLE_MS && (face.status === "recognized" || face.status === "possible_match")) {
      setPrompt({ kind: "confirm", personId: id, name: face.best.display_name, similarity: face.best.similarity, status: face.status });
    } else if (id === "__unknown__" && face.status === "unknown" && stable > UNKNOWN_MS) {
      setPrompt({ kind: "register" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result, running, registering, prompt, pending]);

  const close = (key: string) => {
    answered.current[key] = Date.now();
    setPrompt(null);
    setCorrecting(false);
  };
  const yes = (p: Extract<Prompt, { kind: "confirm" }>) => {
    send({ type: "feedback", verdict: "correct", person_id: p.personId, similarity: p.similarity });
    if (teachOnYes) {
      setPending(p.personId);
      send({ type: "confirm", person_id: p.personId });
    }
    close(p.personId);
  };
  const wrong = (p: Extract<Prompt, { kind: "confirm" }>, correctedId?: string) => {
    send({ type: "feedback", verdict: "wrong", person_id: p.personId, similarity: p.similarity, corrected_person_id: correctedId ?? null });
    if (correctedId) {
      setPending(correctedId);
      send({ type: "confirm", person_id: correctedId });
    }
    close(p.personId);
  };
  useEffect(() => {
    if (taught || refused || note) setPending(null);
  }, [taught, refused, note]);
  useEffect(() => {
    if (!taught) return;
    const timer = window.setTimeout(() => setTaught(null), 6000);
    return () => window.clearTimeout(timer);
  }, [taught, setTaught]);

  if (cameras.isSuccess && live.length === 0)
    return <Notice>The live test needs a camera. Add a webcam or a network camera on the <Link to="/cameras">Cameras</Link> page, or test a picture instead.</Notice>;
  const others = (people.data ?? []).filter((p) => prompt?.kind === "confirm" && p.id !== prompt.personId);
  return (
    <div className="stack">
      <div className="inline-form">
        <Field label="Camera">
          <select value={cameraId} onChange={(e) => setCameraId(e.target.value ? Number(e.target.value) : "")} disabled={running}>
            {live.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </Field>
        {running ? (
          <button className="btn" onClick={() => setRunning(false)}>
            Stop
          </button>
        ) : (
          <button className="btn primary" disabled={cameraId === ""} onClick={() => setRunning(true)}>
            Start live test
          </button>
        )}
        <label className="check">
          <input type="checkbox" checked={teachOnYes} onChange={(e) => setTeachOnYes(e.target.checked)} />
          Keep the picture when I confirm a match
        </label>
        <span className="hint">
          The camera opens only while this runs. Nothing is stored unless you confirm a match or register someone.
        </span>
      </div>
      {error && <ErrorNotice error={error} />}
      {counts && counts.checked > 0 && (
        <div className="row wrap">
          <Pill tone="ok">{counts.correct} confirmed</Pill>
          <Pill tone={counts.wrong ? "warn" : ""}>{counts.wrong} corrected</Pill>
          <Pill tone="">{counts.taught} pictures learned</Pill>
          <span className="hint">Answers are kept in the audit trail. They do not move any threshold by themselves.</span>
        </div>
      )}
      {running && (
        <div className="grid-2">
          <div className="stack">
            <FaceStage src={frameUrl} result={result} mirror={!!ready?.mirror} />
            {prompt?.kind === "confirm" && (
              <div className="ask">
                <div className="ask-q">
                  Is this <strong>{prompt.name}</strong>? <span className="muted small">similarity {sim(prompt.similarity)}{prompt.status === "possible_match" ? " · only a possible match" : ""}</span>
                </div>
                {!correcting ? (
                  <div className="row wrap">
                    <button className="btn primary sm" onClick={() => yes(prompt)}>
                      Yes, correct
                    </button>
                    <button className="btn sm" onClick={() => setCorrecting(true)}>
                      No
                    </button>
                    <button className="btn ghost sm" onClick={() => close(prompt.personId)}>
                      Skip
                    </button>
                  </div>
                ) : (
                  <div className="row wrap">
                    <span className="small">Who is it?</span>
                    <select
                      defaultValue=""
                      onChange={(e) => {
                        if (e.target.value) wrong(prompt, e.target.value);
                      }}
                    >
                      <option value="">Someone else…</option>
                      {others.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.display_name}
                        </option>
                      ))}
                    </select>
                    <button className="btn sm" onClick={() => { wrong(prompt); setRegistering(true); }}>
                      Not enrolled — register
                    </button>
                    <button className="btn ghost sm" onClick={() => wrong(prompt)}>
                      Just wrong
                    </button>
                  </div>
                )}
              </div>
            )}
            {prompt?.kind === "register" && (
              <div className="ask">
                <div className="ask-q">Not recognized. Register this person?</div>
                <div className="row wrap">
                  <button
                    className="btn primary sm"
                    onClick={() => {
                      send({ type: "feedback", verdict: "unknown_person" });
                      close("__unknown__");
                      setRegistering(true);
                    }}
                  >
                    Register and teach the views
                  </button>
                  <button className="btn ghost sm" onClick={() => close("__unknown__")}>
                    Not now
                  </button>
                </div>
                <div className="hint">Enrolling is deliberate and needs the person's agreement. Unknown people stay anonymous until then.</div>
              </div>
            )}
            {pending && <div className="hint">Adding the picture…</div>}
            {taught && (
              <Notice tone="ok">
                Added to {taught.person.display_name} ({taught.look}): {taught.person.n_templates} templates now
                {taught.similarity != null ? `, this picture matched at ${sim(taught.similarity)}` : ""}.
              </Notice>
            )}
            {refused && (
              <Notice tone="warn">
                {refused.message}
                {refused.code === "mismatch" && prompt === null && (
                  <div className="row" style={{ marginTop: 6 }}>
                    <button className="btn sm" onClick={() => send({ type: "confirm", person_id: seen.current.id && seen.current.id !== "__unknown__" ? seen.current.id : (face?.best?.identity_id ?? ""), force: true })}>
                      Add anyway
                    </button>
                  </div>
                )}
              </Notice>
            )}
            {note && <Notice tone={note.level === "err" ? "err" : "warn"}>{note.message}</Notice>}
          </div>
          <div className="stack">
            {!connected && <div className="hint">Connecting…</div>}
            {ready && <Thresholds result={ready} />}
            {ready && ready.identities === 0 && (
              <Notice tone="warn">
                Nobody is enrolled for these models, so every face reads Unknown. Register the person in front of the camera, or enroll under <Link to="/recognition/people">People</Link>.
              </Notice>
            )}
            {result ? <ResultDetail result={result} /> : <div className="hint">Step in front of the camera.</div>}
          </div>
        </div>
      )}
      {registering && cameraId !== "" && (
        <RegisterFromTest
          cameraId={Number(cameraId)}
          onDone={() => {
            setRegistering(false);
            answered.current = {};
            qc.invalidateQueries({ queryKey: ["recognition-people"] });
          }}
          onClose={() => setRegistering(false)}
        />
      )}
    </div>
  );
}

function PictureTest() {
  const [file, setFile] = useState<File | null>(null);
  const [src, setSrc] = useState<string | null>(null);
  const [result, setResult] = useState<IdentifyResult | null>(null);
  const [teachTo, setTeachTo] = useState("");
  const [taught, setTaught] = useState<string | null>(null);
  const [needsForce, setNeedsForce] = useState<string | null>(null);
  const qc = useQueryClient();
  const people = useQuery({ queryKey: ["recognition-people"], queryFn: api.recognition.people });
  const identify = useMutation({
    mutationFn: () => api.recognition.identifyFile(file!),
    onSuccess: (r) => {
      setResult(r);
      setTaught(null);
      setNeedsForce(null);
      setTeachTo(r.faces[0]?.best?.identity_id ?? "");
    },
  });
  const teach = useMutation({
    mutationFn: (force: boolean) => api.recognition.teach(teachTo, file!, "", force),
    onSuccess: (r) => {
      setTaught(`Added to ${r.person.display_name}: ${r.person.n_templates} templates now${r.similarity != null ? `, matched at ${sim(r.similarity)}` : ""}.`);
      setNeedsForce(null);
      qc.invalidateQueries({ queryKey: ["recognition-people"] });
      qc.invalidateQueries({ queryKey: ["recognition-enrollment-check"] });
    },
    onError: (e: unknown) => {
      const msg = e instanceof Error ? e.message : String(e);
      setNeedsForce(msg.includes("Confirm again") ? msg : null);
    },
  });
  const feedback = useMutation({ mutationFn: (verdict: "correct" | "wrong") => api.recognition.testFeedback({ verdict, person_id: result?.faces[0]?.best?.identity_id ?? null, similarity: result?.faces[0]?.best?.similarity ?? null, source: "picture" }) });
  const cameras = useQuery({ queryKey: ["cameras", "all"], queryFn: () => api.cameras.list() });
  const [cameraId, setCameraId] = useState<number | "">("");
  const grab = useMutation({
    mutationFn: () => api.recognition.identifyCamera(Number(cameraId)),
    onSuccess: (r) => {
      setResult(r);
      setSrc(null);
    },
  });
  useEffect(() => {
    if (!file) return;
    const url = URL.createObjectURL(file);
    setSrc(url);
    setResult(null);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  return (
    <div className="stack">
      <div className="inline-form">
        <Field label="Picture (JPEG or PNG)">
          <input type="file" accept="image/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </Field>
        <button className="btn primary" disabled={!file || identify.isPending} onClick={() => identify.mutate()}>
          Identify
        </button>
        <span className="divider" />
        <Field label="or one frame from">
          <select value={cameraId} onChange={(e) => setCameraId(e.target.value ? Number(e.target.value) : "")}>
            <option value="">a camera…</option>
            {cameras.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </Field>
        <button className="btn" disabled={cameraId === "" || grab.isPending} onClick={() => grab.mutate()}>
          Take a frame and identify
        </button>
      </div>
      {identify.isError && <ErrorNotice error={identify.error} />}
      {grab.isError && <ErrorNotice error={grab.error} />}
      {result && (
        <div className="grid-2">
          <FaceStage src={src} result={result} />
          <div className="stack">
            <Thresholds result={result} />
            <ResultDetail result={result} />
            {file && result.n_faces > 0 && (
              <div className="ask">
                <div className="ask-q">Was that right?</div>
                <div className="row wrap">
                  {result.faces[0].best && (
                    <button className="btn sm" disabled={feedback.isPending} onClick={() => feedback.mutate("correct")}>
                      Yes, it is {result.faces[0].best!.display_name}
                    </button>
                  )}
                  <button className="btn sm" disabled={feedback.isPending} onClick={() => feedback.mutate("wrong")}>
                    No
                  </button>
                  <span className="divider" />
                  <span className="small">Keep this picture for</span>
                  <select value={teachTo} onChange={(e) => { setTeachTo(e.target.value); setNeedsForce(null); }}>
                    <option value="">nobody</option>
                    {people.data?.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.display_name}
                      </option>
                    ))}
                  </select>
                  <button className="btn primary sm" disabled={!teachTo || teach.isPending} onClick={() => teach.mutate(false)}>
                    Add to enrollment
                  </button>
                </div>
                {needsForce && (
                  <Notice tone="warn">
                    {needsForce}
                    <div className="row" style={{ marginTop: 6 }}>
                      <button className="btn sm" onClick={() => teach.mutate(true)}>
                        Add anyway
                      </button>
                    </div>
                  </Notice>
                )}
                {teach.isError && !needsForce && <ErrorNotice error={teach.error} />}
                {taught && <Notice tone="ok">{taught}</Notice>}
                {feedback.isSuccess && !taught && <div className="hint">Answer recorded.</div>}
              </div>
            )}
          </div>
        </div>
      )}
      <div className="hint">
        The picture is analysed and thrown away: no enrollment image, no template and no recognition event is created. A video file cannot be tested here; take a frame from its camera above.
      </div>
    </div>
  );
}

function PersonRow({ p }: { p: EnrollmentCheckPerson }) {
  const v = VERDICT[p.verdict] ?? VERDICT.ok;
  return (
    <tr>
      <td>
        <Link to="/recognition/people">{p.display_name}</Link>
        {p.reference_id ? <span className="muted small"> {p.reference_id}</span> : null}
      </td>
      <td>
        <Pill tone={v.tone}>{v.label}</Pill>
      </td>
      <td className="num">{p.templates}</td>
      <td>{p.views.join(", ") || "–"}</td>
      <td>{p.n_looks === 0 ? "–" : p.looks.map((l) => l || "first enrollment").join(", ")}</td>
      <td className="num">{p.self_similarity != null ? num(p.self_similarity, 2) : "–"}</td>
      <td>{p.nearest_other ? `${p.nearest_other.display_name} ${num(p.nearest_other.similarity, 2)}` : "–"}</td>
      <td className="small">
        {p.advice.map((a) => (
          <div key={a}>{a}</div>
        ))}
      </td>
    </tr>
  );
}

function EnrollmentCheckPanel() {
  const q = useQuery({ queryKey: ["recognition-enrollment-check"], queryFn: api.recognition.enrollmentCheck, retry: 0 });
  if (q.isError) return <ErrorNotice error={q.error} />;
  if (!q.data) return <div className="hint">Checking…</div>;
  const d = q.data;
  return (
    <div className="stack">
      <div className="row wrap">
        <Pill tone={d.counts.ok ? "ok" : ""}>{d.counts.ok} healthy</Pill>
        <Pill tone={d.counts.weak ? "warn" : ""}>{d.counts.weak} need more pictures</Pill>
        <Pill tone={d.counts.risk ? "err" : ""}>{d.counts.risk} mix-up risk</Pill>
        <Pill tone={d.counts.blocked ? "err" : ""}>{d.counts.blocked} not matched</Pill>
        <span className="hint">
          A profile is compared with its own pictures and with everyone else. Two people above {num(d.possible_threshold, 2)} can be confused for each other.
        </span>
      </div>
      {d.people.length === 0 ? (
        <Empty>
          Nobody is enrolled yet. Create a profile under <Link to="/recognition/people">People</Link>.
        </Empty>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Person</th>
                <th>Verdict</th>
                <th className="num">Templates</th>
                <th>Views</th>
                <th>Looks</th>
                <th className="num" title="How well the person's own pictures agree">Own pictures</th>
                <th title="The closest other enrolled person">Nearest other</th>
                <th>What would help</th>
              </tr>
            </thead>
            <tbody>
              {d.people.map((p) => (
                <PersonRow key={p.id} p={p} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="hint">
        Models {d.model_version || "–"} · {d.min_views} views required · pictures of one person must agree at {num(d.min_consistency, 2)}.
      </div>
    </div>
  );
}

export default function RecognitionTestPage() {
  const me = usePrincipal();
  const status = useRecognitionStatus();
  const [tab, setTab] = useState("live");
  const canTest = roleAtLeast(me.data?.role, "operator");
  const face = status.data?.modules.face;
  return (
    <RecognitionGate title="Test recognition" sub="Check whether faces are recognized here, and whether an enrollment is strong enough. Nothing is stored.">
      {face && !face.licensed && face.state !== "disabled" && (
        <Notice tone="warn">
          Face recognition is {face.state.replace("_", " ")}. The test needs a licensed module; see <Link to="/recognition/settings">Settings</Link>.
        </Notice>
      )}
      {face?.licensed && !face.models_ready && (
        <Notice tone="warn">
          The face models are not installed. Install them on the <Link to="/models">Models</Link> page.
        </Notice>
      )}
      {!canTest ? (
        <Notice>Testing needs the operator role; a viewer token can read the recognition events instead.</Notice>
      ) : (
        <>
          <Tabs
            tabs={[
              { id: "live", label: "Live camera" },
              { id: "picture", label: "A picture" },
              { id: "enrollment", label: "Enrollment check" },
            ]}
            active={tab}
            onChange={setTab}
          />
          <Panel
            title={tab === "live" ? "Who does this camera recognize?" : tab === "picture" ? "What does the system make of this picture?" : "How strong is each enrollment?"}
          >
            {tab === "live" && <LiveTest />}
            {tab === "picture" && <PictureTest />}
            {tab === "enrollment" && <EnrollmentCheckPanel />}
          </Panel>
        </>
      )}
    </RecognitionGate>
  );
}
