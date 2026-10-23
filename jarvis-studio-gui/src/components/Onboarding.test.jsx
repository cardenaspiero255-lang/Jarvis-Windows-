import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import Onboarding, { buildOnboardingConfig } from "./Onboarding";

describe("first run local-first onboarding", () => {
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
