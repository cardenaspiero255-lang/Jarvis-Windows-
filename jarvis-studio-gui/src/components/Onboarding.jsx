import { useState } from "react";

export function buildOnboardingConfig({ storageDir, groqKey, geminiKey, useOffline }) {
  const cfg = { storage_dir: storageDir.trim() };
  if (useOffline) {
    // Reuse the existing Ollama implementation; no simulated provider key.
    cfg.provider_mode = "offline";
  }
  if (groqKey.trim()) cfg.groq_api_key = groqKey.trim();
  if (geminiKey.trim()) cfg.gemini_api_key = geminiKey.trim();
  return cfg;
}

/* First-run setup. Shown whenever the backend reports `needs_setup` (no API key
   yet, or no storage location chosen). Collects at least one API key and a
   storage folder, then hands them to the backend via the same set_config path
   the Settings panel uses. Keys are stored in app data — never in committed
   source. */
export default function Onboarding({ sysInfo, onSave }) {
  const defaultStorage = sysInfo.storage_dir || "";
  const [groqKey, setGroqKey] = useState("");
  const [geminiKey, setGeminiKey] = useState("");
  const [storageDir, setStorageDir] = useState(defaultStorage);
  const [touched, setTouched] = useState(false);
  const [useOffline, setUseOffline] = useState(false);

  const hasAnyKey = useOffline || groqKey.trim() || geminiKey.trim() || sysInfo.has_groq_key || sysInfo.has_gemini_key;
  const hasStorage = storageDir.trim().length > 0;
  const canFinish = hasAnyKey && hasStorage;

  const finish = () => {
    setTouched(true);
    if (!canFinish) return;
    onSave(buildOnboardingConfig({ storageDir, groqKey, geminiKey, useOffline }));
  };

  return (
    <div className="onboard-overlay">
      <div className="onboard-panel" role="dialog" aria-label="Welcome to JARVIS">
        <div className="onboard-hd">
          <span className="onboard-kicker">First-run setup</span>
          <h2>Welcome to JARVIS</h2>
          <p className="onboard-sub">
            Choose local Ollama (no cloud key), or configure a cloud provider.
            Then choose where JARVIS stores your files. You can switch modes in Settings.
          </p>
        </div>

        <div className="onboard-sec">
          <label style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <input type="checkbox" checked={useOffline}
              onChange={(e) => setUseOffline(e.target.checked)} />
            Use local Ollama (no API key)
          </label>
          <span className="onboard-hint">
            JARVIS already supports offline Ollama. Start your local Ollama service
            and download a model separately; no cloud account is required.
            Existing cloud keys are never sent to Ollama.
          </span>
        </div>
        <div className="onboard-sec">
          <label>Groq API keys {sysInfo.has_groq_key && <span className="onboard-ok">✓ set</span>}</label>
          <textarea rows={2} value={groqKey} onChange={(e) => setGroqKey(e.target.value)}
                    placeholder="gsk_…  (groq.com/keys)" />
        </div>

        <div className="onboard-sec">
          <label>Gemini API keys {sysInfo.has_gemini_key && <span className="onboard-ok">✓ set</span>}</label>
          <textarea rows={2} value={geminiKey} onChange={(e) => setGeminiKey(e.target.value)}
                    placeholder="AIza…  (aistudio.google.com/apikey)" />
          <span className="onboard-hint">
            Free-tier limits are counted per key. Paste as many as you have, one per line,
            and I'll rotate through them instead of stopping at a rate limit.
          </span>
        </div>

        <div className="onboard-sec">
          <label>Storage folder</label>
          <input type="text" value={storageDir} onChange={(e) => setStorageDir(e.target.value)}
                 placeholder="C:\Users\you\Jarvis" />
          <span className="onboard-hint">
            Created if it doesn't exist, with images / recordings / documents subfolders.
          </span>
        </div>

        {touched && !canFinish && (
          <div className="onboard-warn">
            {!hasAnyKey ? "Choose local Ollama or add an API key to continue." : "Choose a storage folder to continue."}
          </div>
        )}

        <button className="onboard-go" disabled={!canFinish} onClick={finish}>
          Start JARVIS →
        </button>
      </div>
    </div>
  );
}
