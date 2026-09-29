import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { Camera, SceneDocument } from "../api/types";
import SceneOverlay, { SceneLegend } from "./SceneOverlay";
import { useLocalState } from "./ui";

/** What a camera sees: a live stream for cameras, the first frame for video files.
 *  While a run uses the camera, the stream shows the run's frames with a box
 *  around each tracked object (drawn by the API for MJPEG viewers).
 *
 *  With a ``scene``, its zones, lines and routes are drawn over the picture with
 *  the names rules use (and each line's forward direction); with the view off,
 *  they are drawn on the frame's outline. ``highlight`` emphasizes objects,
 *  for example the ones a rule refers to. */
export function CameraView({ camera, maxHeight = 280, scene, sceneLabel, highlight }: { camera: Camera; maxHeight?: number; scene?: SceneDocument | null; sceneLabel?: string; highlight?: string[] }) {
  const live = camera.source_type !== "file";
  const [on, setOn] = useState(true);
  const [failed, setFailed] = useState(false);
  const [showScene, setShowScene] = useLocalState("pathscope.cameraView.scene", true);
  const [large, setLarge] = useLocalState("pathscope.cameraView.large", false);
  const [hover, setHover] = useState<string[] | null>(null);
  const src = useMemo(() => (live ? api.cameras.previewUrl(camera.id) : api.cameras.snapshotUrl(camera.id, 0)), [camera.id, live]);
  // A stream shows nothing until its first frame (a network camera can take a while):
  // until then the scene is drawn on the frame's outline. Browsers differ in
  // firing "load" for MJPEG, so the picture's size is checked as well.
  const img = useRef<HTMLImageElement>(null);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    setLoaded(false);
    if (!on) return;
    const id = window.setInterval(() => {
      if ((img.current?.naturalWidth ?? 0) > 0) {
        setLoaded(true);
        window.clearInterval(id);
      }
    }, 250);
    return () => window.clearInterval(id);
  }, [src, on]);
  const hasScene = !!scene && scene.objects.length > 0;
  const hl = useMemo(() => new Set([...(highlight ?? []), ...(hover ?? [])]), [highlight, hover]);
  const height = large ? Math.max(maxHeight, 540) : maxHeight;
  const overlay = hasScene && showScene ? <SceneOverlay doc={scene!} highlight={hl} onHover={setHover} /> : null;
  const picture = on && !failed;
  const shown = picture && loaded;
  const fw = scene?.frame_width || 16;
  const fh = scene?.frame_height || 9;
  return (
    <div className="camera-view-wrap">
      <div className="camera-view" style={{ minHeight: on || overlay ? 120 : 44 }}>
        {picture && (
          <div className="scene-frame" style={shown ? undefined : { display: "none" }}>
            <img ref={img} key={src} src={src} alt={live ? `Live view of ${camera.name}` : `First frame of ${camera.name}`} style={{ maxHeight: height }} onLoad={() => setLoaded(true)} onError={() => setFailed(true)} />
            {shown && overlay}
          </div>
        )}
        {picture && !shown && !overlay && <span className="hint">Waiting for the first picture…</span>}
        {!shown && overlay && (
          <div className="scene-frame placeholder" style={{ aspectRatio: `${fw} / ${fh}`, height: Math.min(height, 240), maxWidth: "100%" }}>
            {overlay}
          </div>
        )}
        {on && failed && !overlay && <span className="hint">No picture from this camera. Check it on the Cameras page with Test connection.</span>}
        {!on && !overlay && <span className="hint">Camera view is off.</span>}
      </div>
      <div className="row hint" style={{ marginTop: 4, justifyContent: "space-between" }}>
        <span>
          {!shown && overlay
            ? !on
              ? "Camera view is off: the zones and lines are drawn on the frame's outline."
              : failed
                ? "No picture from this camera (check it on the Cameras page); the zones and lines are drawn on the frame's outline."
                : "Waiting for the first picture; until then the zones and lines are drawn on the frame's outline."
            : live
              ? on
                ? "Live view. The camera stays on while it is shown; during a run it shows the run's picture with boxes."
                : "The camera is free for other apps."
              : "First frame of the video."}
        </span>
        {live && (
          <button
            className="btn sm ghost"
            onClick={() => {
              setFailed(false);
              setOn(!on);
            }}
          >
            {on ? "Turn view off" : "Show live view"}
          </button>
        )}
      </div>
      {scene && (
        <div style={{ marginTop: 6 }}>
          <div className="scene-view-tools small">
            {hasScene ? (
              <>
                <label className="check">
                  <input type="checkbox" checked={showScene} onChange={(e) => setShowScene(e.target.checked)} />
                  Show zones and lines{sceneLabel ? ` (${sceneLabel})` : ""}
                </label>
                <label className="check">
                  <input type="checkbox" checked={large} onChange={(e) => setLarge(e.target.checked)} />
                  Larger view
                </label>
                <span className="hint">Point at a name to find it on the picture; the arrow on a line is its forward direction.</span>
              </>
            ) : (
              <span className="hint">This scene{sceneLabel ? ` (${sceneLabel})` : ""} has no zones or lines yet: draw them in the Scene builder.</span>
            )}
          </div>
          {hasScene && showScene && <SceneLegend doc={scene} highlight={hl} onHover={setHover} />}
        </div>
      )}
    </div>
  );
}
