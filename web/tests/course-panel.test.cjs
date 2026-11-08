const assert = require("node:assert/strict");
const fs = require("node:fs");
const Module = require("node:module");
const path = require("node:path");
const test = require("node:test");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const ts = require("typescript");

function renderCourse(versions, course = {}) {
  const filename = path.resolve(__dirname, "../components/course-panel.tsx");
  const source = fs.readFileSync(filename, "utf8");
  const code = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS } }).outputText;
  const component = new Module(filename, module);
  component.filename = filename;
  component.paths = module.paths;
  const originalRequire = component.require.bind(component);
  component.require = (name) => {
    if (name === "@tanstack/react-query") return {
      useQuery: ({ queryKey }) => queryKey[0] === "course-versions" ? versions : course,
      useMutation: () => ({ isPending: false }),
      useQueryClient: () => ({}),
    };
    if (name === "lucide-react") return { AlertTriangle: () => null, LoaderCircle: () => null, NotebookPen: () => null };
    if (name === "@/components/ui/button") return { Button: (props) => React.createElement("button", props) };
    if (name === "@/components/ui/card") return { Card: (props) => React.createElement("div", props) };
    if (name === "@/lib/api") return {};
    return originalRequire(name);
  };
  component._compile(code, filename);
  return renderToStaticMarkup(React.createElement(component.exports.CoursePanel, { researchRunId: "run", token: "token" }));
}

test("does not offer a new build while course history is unavailable", () => {
  const html = renderCourse({ isError: true, isPending: false, refetch() {} });
  assert.match(html, /Could not load course versions/);
  assert.match(html, /<button[^>]*disabled[^>]*>Build course/);
});

test("shows a retry when an existing course cannot be loaded", () => {
  const html = renderCourse({ data: [{ id: "course", version: 1, status: "completed", created_at: "2026-01-01" }], isPending: false }, { isError: true, refetch() {} });
  assert.match(html, /Could not load the course/);
  assert.match(html, /Try again/);
});
