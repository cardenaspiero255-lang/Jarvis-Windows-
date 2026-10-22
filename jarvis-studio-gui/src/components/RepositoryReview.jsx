import React, { useState } from "react";

// Local desktop consent UI. The backend enforces every state transition;
// presentation never makes an external repo executable or edits the original.
export default function RepositoryReview({
  review, onClose, onInspect, onPropose, onApprove, onRollback, onExport,
}) {
  const [file, setFile] = useState(null);
  const [path, setPath] = useState("");
  const [fn, setFn] = useState("");
  const [confirmed, setConfirmed] = useState(false);

  const status = review?.status;
  const session = review?.session_id;
  const preview = status === "review_required";
  const staged = status === "copy_staged";
  const error = status === "denied";
  const action = (label, handler, disabled = false) => (
    <button type="button" disabled={disabled} onClick={handler}
      style={{ padding: "8px 13px", borderRadius: 8, cursor: "pointer" }}>{label}</button>
  );
  return (
    <div role="dialog" aria-modal="true" aria-label="Repository review"
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.85)",
        zIndex: 10020, overflowY: "auto", display: "grid",
        placeItems: "center", color: "#e8e8ed" }}>
      <div style={{ width: "min(700px, 95vw)", maxHeight: "90vh", overflowY: "auto",
        padding: 20, border: "1px solid #8d232c", borderRadius: 16,
        background: "#141518", display: "grid", gap: 12 }}>
        <header style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
          <strong>JARVIS · Repository Review</strong>
          {action("Close", onClose)}
        </header>
        <p>Static analysis only. External code is never executed, dependencies are not
          installed, and your original repository will not be modified.</p>
        {error && <p role="alert" style={{ color: "#ff9393" }}>{review.error}</p>}
        {!session && (
          <div style={{ display: "grid", gap: 8 }}>
            <label htmlFor="jarvis-repo-zip">Choose a ZIP snapshot (max. 4 MB)</label>
            <input id="jarvis-repo-zip" type="file"
              accept=".zip,application/zip"
              onChange={(e) => setFile(e.target.files?.[0] || null)} />
            {action("Inspect ZIP", () => onInspect(file), !file)}
          </div>
        )}
        {session && <>
          {status === "inspected" && <>
            <p>{review.file_count} files · {(review.languages || []).join(", ")}</p>
            <label htmlFor="jarvis-repo-path">Python source path inside ZIP</label>
            <input id="jarvis-repo-path" value={path} placeholder="src/calc.py"
              onChange={(e) => setPath(e.target.value)} />
            <label htmlFor="jarvis-repo-fn">Function to repair (two numeric parameters)</label>
            <input id="jarvis-repo-fn" value={fn} placeholder="total"
              onChange={(e) => setFn(e.target.value)} />
            <p>The local Ollama model will read this file for a restricted arithmetic
              suggestion. No cloud model is used.</p>
            {action("Generate local proposal",
              () => onPropose(session, path, fn), !path || !fn)}
          </>}
          {preview && <>
            <p>Syntax only — no external tests were run. Inspect the exact diff and
              SHA-256 before approving a modified copy.</p>
            <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere",
              maxHeight: 230, overflowY: "auto",
              background: "#0d0e10", padding: 12 }}>{review.diff}</pre>
            <small style={{ overflowWrap: "anywhere" }}>Reviewed SHA-256: {review.patched_sha256}</small>
            <label style={{ display: "flex", gap: 8 }}>
              <input type="checkbox" checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)} />
              I reviewed this patch. Create only a separate ZIP copy.
            </label>
            {action("Approve modified copy",
              () => onApprove(session, review.patched_sha256), !confirmed)}
          </>}
          {staged && <>
            <p>A modified ZIP copy is prepared in memory. The original is unchanged.</p>
            {action("Download modified ZIP", () => onExport(session))}
            {review.zip_b64 && (
              <a download="jarvis-reviewed-copy.zip"
                href={"data:application/zip;base64," + review.zip_b64}>
                Save reviewed ZIP to this device
              </a>
            )}
          </>}
          {action(staged ? "Discard copy (rollback)" : "Discard review",
            () => { setConfirmed(false); onRollback(session); })}
        </>}
      </div>
    </div>
  );
}
