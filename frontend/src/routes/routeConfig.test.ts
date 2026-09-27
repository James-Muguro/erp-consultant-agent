import { describe, expect, it } from "vitest";
import { ROUTES, matchRouteConfig } from "./routeConfig";

describe("ROUTES", () => {
  it("declares every authenticated route exactly once", () => {
    const paths = ROUTES.map((r) => r.path);
    const expected = [
      "/",
      "/settings",
      "/chat",
      "/chat/:sessionId",
      "/p/:sessionId/chat",
      "/p/:sessionId/:tab",
      "/p/:sessionId",
      "/org/:orgId",
    ];
    for (const p of expected) {
      expect(paths).toContain(p);
    }
    expect(new Set(paths).size).toBe(paths.length);
  });

  it("gates workspace routes on phase:execute", () => {
    for (const p of ["/p/:sessionId/chat", "/p/:sessionId/:tab", "/p/:sessionId"]) {
      const r = ROUTES.find((x) => x.path === p);
      expect(r?.requiredCapability).toBe("phase:execute");
      expect(r?.hasWorkspace).toBe(true);
      expect(r?.organizationScoped).toBeUndefined();
    }
  });

  it("gates chat routes on chat:submit", () => {
    for (const p of ["/chat", "/chat/:sessionId"]) {
      const r = ROUTES.find((x) => x.path === p);
      expect(r?.requiredCapability).toBe("chat:submit");
      expect(r?.hasWorkspace).toBe(false);
    }
  });

  it("leaves / and /settings ungated", () => {
    for (const p of ["/", "/settings"]) {
      const r = ROUTES.find((x) => x.path === p);
      expect(r?.requiredCapability).toBeUndefined();
      expect(r?.organizationScoped).toBeUndefined();
    }
  });

  it("marks the organization route as organizationScoped and ungated", () => {
    const r = ROUTES.find((x) => x.path === "/org/:orgId");
    expect(r?.organizationScoped).toBe(true);
    expect(r?.requiredCapability).toBeUndefined();
    expect(r?.hasWorkspace).toBe(false);
  });
});

describe("matchRouteConfig", () => {
  it("matches the root path", () => {
    const r = matchRouteConfig("/");
    expect(r?.path).toBe("/");
    expect(r?.hasWorkspace).toBe(false);
  });

  it("matches settings", () => {
    expect(matchRouteConfig("/settings")?.path).toBe("/settings");
  });

  it("marks adhoc chat as NOT a workspace", () => {
    expect(matchRouteConfig("/chat")?.hasWorkspace).toBe(false);
    expect(matchRouteConfig("/chat/prj_abc")?.hasWorkspace).toBe(false);
  });

  it("marks project workspace root as a workspace", () => {
    expect(matchRouteConfig("/p/prj_abc")?.hasWorkspace).toBe(true);
  });

  it("marks a project workspace tab as a workspace", () => {
    expect(matchRouteConfig("/p/prj_abc/requirements")?.hasWorkspace).toBe(true);
  });

  it("matches project chat against its dedicated route, not the generic tab", () => {
    expect(matchRouteConfig("/p/prj_abc/chat")?.path).toBe("/p/:sessionId/chat");
  });

  it("matches organization routes", () => {
    const r = matchRouteConfig("/org/org_abc");
    expect(r?.path).toBe("/org/:orgId");
    expect(r?.organizationScoped).toBe(true);
  });

  it("returns null for an unmatched path", () => {
    expect(matchRouteConfig("/definitely-not-a-route")).toBeNull();
  });
});