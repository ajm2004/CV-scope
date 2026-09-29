import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { RecognitionStatus } from "../api/types";
import { ErrorNotice, Field, Notice, Panel, Pill } from "../components/ui";
import { MODULE_STATE_LABEL, moduleStateTone, ROLE_LABEL, useRecognitionAuth } from "../lib/recognitionToken";
import { usePrincipal, useRecognitionStatus } from "./hooks";

export function ModuleStatusPills({ status }: { status: RecognitionStatus | undefined }) {
  if (!status) return null;
  return (
    <span className="row wrap" style={{ gap: 6 }}>
      {(["face", "plate"] as const).map((m) => {
        const st = status.modules[m];
        return (
          <Pill key={m} tone={moduleStateTone(st.state)} dot>
            {m === "face" ? "Face" : "Plate"}: {MODULE_STATE_LABEL[st.state]}
          </Pill>
        );
      })}
    </span>
  );
}

export function TokenEntry({ status }: { status: RecognitionStatus | undefined }) {
  const setToken = useRecognitionAuth((s) => s.setToken);
  const qc = useQueryClient();
  const [value, setValue] = useState("");
  const [issued, setIssued] = useState<string | null>(null);
  const bootstrap = useMutation({
    mutationFn: () => api.recognition.bootstrap("Administrator"),
    onSuccess: (r) => {
      setIssued(r.token);
      setToken(r.token);
      qc.invalidateQueries({ queryKey: ["recognition-status"] });
    },
  });
  return (
    <Panel title="Access to the recognition modules">
      <p className="small muted">
        Recognition data is sensitive. It is only shown to browsers that present a recognition access token, which an administrator creates under Recognition → Settings → Access tokens (or with <code>cvscope recognition token</code>). Roles: viewer, operator, administrator.
      </p>
      {issued && (
        <Notice tone="ok">
          Your administrator token, shown once. It is stored in this browser; keep a copy somewhere safe: <code className="mono">{issued}</code>
        </Notice>
      )}
      {status && !status.access.has_tokens && !issued && (
        <div className="row" style={{ marginBottom: 10 }}>
          <button className="btn primary" disabled={bootstrap.isPending} onClick={() => bootstrap.mutate()}>
            Create the first administrator token
          </button>
          <span className="hint">Only possible from the computer running CV-Scope, and only while no token exists.</span>
        </div>
      )}
      {bootstrap.isError && <ErrorNotice error={bootstrap.error} />}
      <div className="inline-form">
        <Field label="Recognition access token">
          <input type="password" value={value} placeholder="psr_…" onChange={(e) => setValue(e.target.value)} style={{ minWidth: 320 }} />
        </Field>
        <button className="btn" disabled={!value.trim()} onClick={() => setToken(value.trim())}>
          Use token
        </button>
      </div>
    </Panel>
  );
}

export default function RecognitionGate({ title, sub, children, requireToken = true }: { title: string; sub?: React.ReactNode; children: React.ReactNode; requireToken?: boolean }) {
  const status = useRecognitionStatus();
  const token = useRecognitionAuth((s) => s.token);
  const setToken = useRecognitionAuth((s) => s.setToken);
  const me = usePrincipal();
  const locked = status.data && !status.data.any_licensed;
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>{title}</h1>
          {sub && <div className="sub">{sub}</div>}
        </div>
        <div className="row wrap">
          <ModuleStatusPills status={status.data} />
          {token && me.data && (
            <>
              <Pill tone="accent">
                {me.data.name} · {ROLE_LABEL[me.data.role] ?? me.data.role}
              </Pill>
              <button className="btn sm ghost" onClick={() => setToken(null)}>
                Sign out
              </button>
            </>
          )}
        </div>
      </div>
      {status.isError && <ErrorNotice error={status.error} />}
      {locked && (
        <Notice tone="warn">
          The recognition modules are not licensed on this installation. Nothing is recognized and rules with a recognition condition stay inactive. See <Link to="/recognition/settings">Recognition → Settings</Link> for the licence status.
        </Notice>
      )}
      {requireToken && !token && <TokenEntry status={status.data} />}
      {requireToken && token && me.isError && (
        <Notice tone="err">
          This recognition token is not accepted (revoked, expired or mistyped).{" "}
          <button className="btn sm" onClick={() => setToken(null)}>
            Enter another token
          </button>
        </Notice>
      )}
      {(!requireToken || (token && me.data)) && children}
    </div>
  );
}
