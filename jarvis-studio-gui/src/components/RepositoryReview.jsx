import React, { useState } from "react";

// Local desktop consent UI. The backend enforces every state transition;
// presentation never makes an external repo executable or edits the original.
export default function RepositoryReview({
  review, onClose, onInspect, onPropose, onApprove, onRollback, onExport, onStageGit,
}) {
  const [file, setFile] = useState(null);
  const [path, setPath] = useState("");
  const [fn, setFn] = useState("");
  const [goal, setGoal] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [repoRoot, setRepoRoot] = useState("");
  const [gitConfirmed, setGitConfirmed] = useState(false);

  const status = review?.status;
  const session = review?.session_id;
  const preview = status === "review_required";
  const staged = status === "copy_staged";
  const gitStaged = status === "git_branch_staged";
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
        {error && <p role="alert" style={{ color: "#ff9393" }}>{review.error}{review.reason_code ? ` (${review.reason_code})` : ""}</p>}
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
            <label htmlFor="jarvis-repair-goal">Desired arithmetic behavior (one line)</label>
            <input id="jarvis-repair-goal" value={goal} maxLength={200}
              placeholder="Multiply the price by the quantity"
              onChange={(e) => setGoal(e.target.value)} />
            <p>The local Ollama model will read the selected file as untrusted data
              and propose a restricted arithmetic change for your stated goal.
              No cloud model is used.</p>
            {action("Generate local proposal",
              () => onPropose(session, path, fn, goal), !path || !fn || !goal.trim())}
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
            <p>Optionally stage the reviewed change on a NEW branch of a clean Git repository.
              JARVIS will preserve a private recovery ZIP and leave the original checkout unchanged.
              This does not run project tests or publish a commit.</p>
            <label htmlFor="jarvis-git-root">Authorized clean Git repository root (absolute path)</label>
            <input id="jarvis-git-root" value={repoRoot} placeholder="C:\\projects\\my-project"
              onChange={(e) => setRepoRoot(e.target.value)} />
            <label style={{ display: "flex", gap: 8 }}>
              <input type="checkbox" checked={gitConfirmed}
                onChange={(e) => setGitConfirmed(e.target.checked)} />
              I authorize creating a temporary branch in this clean Git repository,
              using only the exact SHA-256-reviewed file.
            </label>
            {action("Stage Git branch",
              () => onStageGit(session, repoRoot, review.patched_sha256),
              !gitConfirmed || !repoRoot.trim())}
            {review.zip_b64 && (
              <a download="jarvis-reviewed-copy.zip"
                href={"data:application/zip;base64," + review.zip_b64}>
                Save reviewed ZIP to this device
              </a>
            )}
          </>}
          {gitStaged && <>
            <p>The reviewed patch is on a temporary linked Git branch.
              The original checkout is unchanged and no tests were executed.</p>
            <small style={{ overflowWrap: "anywhere" }}>Branch: {review.branch}</small>
            <small style={{ overflowWrap: "anywhere" }}>Recovery archive: {review.backup_path}</small>
            <small style={{ overflowWrap: "anywhere" }}>Staged worktree: {review.worktree}</small>
          </>}
          {action(gitStaged ? "Rollback Git branch" :
            staged ? "Discard copy (rollback)" : "Discard review",
            () => { setConfirmed(false); onRollback(session); })}
        </>}
      </div>
    </div>
  );
}
