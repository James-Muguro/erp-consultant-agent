import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ProjectWorkspace } from "./ProjectWorkspace";
import { useCapabilities } from "../../auth/useCapabilities";
import type { Capabilities } from "../../auth/useCapabilities";

vi.mock("../../auth/useCapabilities", () => ({ useCapabilities: vi.fn() }));

vi.mock("./HealthOverview", () => ({
  HealthOverview: () => <div data-testid="body-overview" />,
}));
vi.mock("./RequirementsList", () => ({
  RequirementsList: () => <div data-testid="body-requirements" />,
}));
vi.mock("./ProcessStepsList", () => ({
  ProcessStepsList: () => <div data-testid="body-process" />,
}));
vi.mock("./SolutionDecisionsList", () => ({
  SolutionDecisionsList: () => <div data-testid="body-solution" />,
}));
vi.mock("./TestingTrainingList", () => ({
  TestingTrainingList: () => <div data-testid="body-testing" />,
}));
vi.mock("./IssuesList", () => ({
  IssuesList: () => <div data-testid="body-issues" />,
}));
vi.mock("./DeliverablesPanel", () => ({
  DeliverablesPanel: () => <div data-testid="body-deliverables" />,
}));
vi.mock("./UploadsPanel", () => ({
  UploadsPanel: () => <div data-testid="body-documents" />,
}));

const mockedUseCapabilities = vi.mocked(useCapabilities);

function makeCapabilities(held: Set<string>): Capabilities {
  return {
    roles: new Set(),
    permissions: new Set(),
    can: (p) => held.has(p),
    isInOrganization: () => false,
    canInOrganization: () => false,
  };
}

function renderAt(path: string, held: string[]) {
  mockedUseCapabilities.mockReturnValue(makeCapabilities(new Set(held)));
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/p/:sessionId" element={<ProjectWorkspace sessionId="prj_1" />} />
        <Route path="/p/:sessionId/:tab" element={<ProjectWorkspace sessionId="prj_1" />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

const FULL_WORKSPACE = [
  "health:read",
  "requirements:read",
  "process_steps:read",
  "solution:read",
  "testing:read",
  "issues:read",
  "documents:read",
  "uploads:read",
];

describe("ProjectWorkspace tab filtering", () => {
  it("shows every tab when the caller holds every capability", () => {
    renderAt("/p/prj_1", FULL_WORKSPACE);
    for (const label of [
      "Overview",
      "Requirements",
      "Process steps",
      "Solution decisions",
      "Testing & training",
      "Issues",
      "Deliverables",
      "Uploads",
    ]) {
      expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    }
  });

  it("hides tabs the caller cannot see", () => {
    renderAt("/p/prj_1", ["health:read", "requirements:read"]);
    expect(screen.getByRole("tab", { name: "Overview" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Requirements" })).toBeInTheDocument();
    expect(
      screen.queryByRole("tab", { name: "Solution decisions" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("tab", { name: "Uploads" }),
    ).not.toBeInTheDocument();
  });

  it("renders the default tab body when no tab is in the URL", () => {
    renderAt("/p/prj_1", FULL_WORKSPACE);
    expect(screen.getByTestId("body-overview")).toBeInTheDocument();
  });

  it("renders the requested tab body when authorized", () => {
    renderAt("/p/prj_1/requirements", FULL_WORKSPACE);
    expect(screen.getByTestId("body-requirements")).toBeInTheDocument();
  });

  it("renders the inline NotAuthorizedState when the requested tab is not held", () => {
    renderAt("/p/prj_1/solution", ["health:read", "requirements:read"]);
    expect(screen.queryByTestId("body-solution")).not.toBeInTheDocument();
    expect(
      screen.getByText(/you don't have access to this section/i),
    ).toBeInTheDocument();
  });
});