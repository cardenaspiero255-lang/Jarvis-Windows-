import { Icon } from "../hud/icons";

// This component is intentionally presentation-only: the backend checks every
// permission response and is the sole authority for executing gated operations.
export default function PermissionDialog({ request, onRespond }) {
  if (!request) return null;

  return (
    <div className="perm-overlay">
      <div className="perm-dialog" role="alertdialog" aria-modal="true"
           aria-label="Permission required" aria-describedby="jarvis-perm-description">
        <div className="perm-icon"><Icon name="warning" size={34} stroke={1.4} /></div>
        <div className="perm-kicker">Your approval is needed</div>
        <div className="perm-desc" id="jarvis-perm-description">
          JARVIS wants to <strong>{request.description}</strong>.
        </div>
        <div className="perm-sub">This action needs your explicit approval.</div>
        <div className="perm-actions">
          <button type="button" className="perm-deny" autoFocus
                  onClick={() => onRespond(request.id, false)}>Deny</button>
          <button type="button" className="perm-approve"
                  onClick={() => onRespond(request.id, true)}>Allow</button>
        </div>
      </div>
    </div>
  );
}
