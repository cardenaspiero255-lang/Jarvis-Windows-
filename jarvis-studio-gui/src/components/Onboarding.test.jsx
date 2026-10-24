import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import Onboarding, { buildOnboardingConfig } from "./Onboarding";
import * as onboardingExports from "./Onboarding";

describe("first run local-first onboarding", () => {
  it("keeps the setup state pending until backend sysinfo arrives, then follows its acknowledgement", () => {
    const derive = onboardingExports.backendSetupState;
    expect(derive?.(false, { needs_setup: false })).toBe("pending");
    expect(derive?.(true, {})).toBe("pending");
    expect(derive?.(true, { needs_setup: true })).toBe("required");
    expect(derive?.(true, { needs_setup: false })).toBe("complete");
  });

  it("offers an explicit offline Ollama option without inventing cloud credentials", () => {
    const html = renderToStaticMarkup(
      <Onboarding sysInfo={{ needs_setup: true, storage_dir: "", has_groq_key: false, has_gemini_key: false }} onSave={() => {}} />
    );
    expect(html).toContain("Use local Ollama (no API key)");
    expect(html).toContain('type="checkbox"');
    expect(html).toContain("Start JARVIS");
  });
  it("saves an explicit offline provider and selected storage without cloud keys", () => {
    expect(buildOnboardingConfig({
      storageDir: "C:\\JarvisOffline", groqKey: "", geminiKey: "", useOffline: true
    })).toEqual({ storage_dir: "C:\\JarvisOffline", provider_mode: "offline" });
  });
  it("keeps traditional cloud onboarding without silently switching to offline", () => {
    expect(buildOnboardingConfig({
      storageDir: " C:\\JarvisCloud ", groqKey: " gsk_test ", geminiKey: "", useOffline: false
    })).toEqual({ storage_dir: "C:\\JarvisCloud", groq_api_key: "gsk_test" });
  });
});
