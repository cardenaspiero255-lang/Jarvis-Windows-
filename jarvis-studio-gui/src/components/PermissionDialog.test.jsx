import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import React from "react";
import PermissionDialog from "./PermissionDialog";

describe("Windows permission dialog", () => {
  it("renders PR authorization as an accessible modal with explicit Allow and Deny", () => {
    const html = renderToStaticMarkup(
      <PermissionDialog
        request={{ id: "req1", kind: "github_pr_read", description: "review GitHub PR #7" }}
        onRespond={() => {}}
      />
    );
    expect(html).toContain('role="alertdialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain("review GitHub PR #7");
    expect(html).toContain("Allow");
    expect(html).toContain("Deny");
  });

  it("escapes injected HTML from untrusted permission descriptions", () => {
    const html = renderToStaticMarkup(
      <PermissionDialog
        request={{ id: "req2", description: '<img src=x onerror="alert(1)">' }}
        onRespond={() => {}}
      />
    );
    expect(html).not.toContain("<img src=x");
    expect(html).toContain("&lt;img");
  });

  it("does not display a permission modal without a pending request", () => {
    expect(renderToStaticMarkup(<PermissionDialog request={null} onRespond={() => {}} />)).toBe("");
  });
});
