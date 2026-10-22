import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import RepositoryReview from "./RepositoryReview";

const noop = () => {};

const defaults = {
  onClose: noop, onInspect: noop, onPropose: noop,
  onApprove: noop, onRollback: noop, onExport: noop,
};

describe("Windows repository review authorization", () => {
  it("shows only inspection before a ZIP has been vetted", () => {
    const html = renderToStaticMarkup(
      <RepositoryReview {...defaults} review={null} />
    );
    expect(html).toContain('accept=".zip,application/zip"');
    expect(html).toContain("Inspect ZIP");
    expect(html).not.toContain("Approve modified copy");
    expect(html).not.toContain("Run tests");
  });

  it("shows preview but cannot approve until there is a reviewed diff", () => {
    const html = renderToStaticMarkup(
      <RepositoryReview {...defaults} review={{
        status: "inspected", file_count: 4, languages: ["python", "typescript"],
        session_id: "session-1",
      }} />
    );
    expect(html).toContain("Generate local proposal");
    expect(html).not.toContain("Approve modified copy");
    expect(html).toContain("Discard review");
  });

  it("shows exact hash, escaped code diff and explicit approval", () => {
    const html = renderToStaticMarkup(
      <RepositoryReview {...defaults} review={{
        status: "review_required", session_id: "session-1",
        patched_sha256: "1".repeat(64),
        diff: '<img src=x onerror="alert(1)">',
        verification: "ast_syntax_only_no_external_tests",
      }} />
    );
    expect(html).toContain("Approve modified copy");
    expect(html).toContain("1".repeat(64));
    expect(html).not.toContain("<img src=x");
    expect(html).toContain("&lt;img");
    expect(html).toContain("Syntax only");
  });

  it("allows export and rollback only when a reviewed copy exists", () => {
    const html = renderToStaticMarkup(
      <RepositoryReview {...defaults} review={{
        status: "copy_staged", session_id: "session-1",
      }} />
    );
    expect(html).toContain("Download modified ZIP");
    expect(html).toContain("Discard copy (rollback)");
    expect(html).not.toContain("Approve modified copy");
  });

  it("offers independently authorized Git staging only after an approved ZIP", () => {
    const html = renderToStaticMarkup(
      <RepositoryReview {...defaults} onStageGit={noop} review={{
        status: "copy_staged", session_id: "s",
        patched_sha256: "a".repeat(64),
      }} />
    );
    expect(html).toContain("Stage Git branch");
    expect(html).toContain("clean Git repository");
    expect(html).toContain("original checkout");
    expect(html).not.toContain("Apply directly to main");
  });

  it("shows local branch, persistent backup and rollback without publishing", () => {
    const html = renderToStaticMarkup(
      <RepositoryReview {...defaults} onStageGit={noop} review={{
        status: "git_branch_staged", session_id: "s",
        branch: "jarvis/review-abc123",
        backup_path: "/recovery/recovery.zip",
      }} />
    );
    expect(html).toContain("jarvis/review-abc123");
    expect(html).toContain("recovery.zip");
    expect(html).toContain("Rollback Git branch");
    expect(html).not.toContain("Publish branch");
  });

  it("shows rejected actions without a fake success claim", () => {
    const html = renderToStaticMarkup(
      <RepositoryReview {...defaults} review={{
        status: "denied", error: "Request rejected",
      }} />
    );
    expect(html).toContain("Request rejected");
    expect(html).not.toContain("Download modified ZIP");
  });
});
