import { defineRailway, project, service } from "railway/iac";

// This repository manages only its own resources in the environment. Other
// repositories export their own partial name.
// See https://docs.railway.com/infrastructure-as-code#multi-repo-projects
export const partial = "LCC";

export default defineRailway(() => {
  const LCC = service("LCC", {
    // The repo-root Dockerfile is the route-eval harness; this one serves MCP.
    dockerfilePath: "docker/Dockerfile.chatgpt",
    start: "lcc mcp --http --host 0.0.0.0 --port $PORT",
    // GET /health answers 200; without this the edge reports 502 on a live app.
    healthcheck: "/health",
  });
  return project("lcc-chatgpt", {
    resources: [LCC],
  });
});
