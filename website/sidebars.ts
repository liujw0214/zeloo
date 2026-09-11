import type { SidebarsConfig } from "@docusaurus/plugin-content-docs";

const sidebars: SidebarsConfig = {
  ZelooSidebar: [
    "intro",
    {
      type: "category",
      label: "Getting Started",
      items: [
        "getting-started/installation",
        "getting-started/quickstart",
        "getting-started/configuration",
      ],
    },
    {
      type: "category",
      label: "Architecture",
      items: [
        "architecture/overview",
        "architecture/agent-loop",
        "architecture/system-prompt",
        "architecture/memory",
      ],
    },
    {
      type: "category",
      label: "Modules",
      items: [
        "modules/tools",
        "modules/mcp",
        "modules/skills",
        "modules/plugins",
        "modules/state",
      ],
    },
    {
      type: "category",
      label: "Deployment",
      items: [
        "deployment/cli",
        "deployment/docker",
        "deployment/cicd",
      ],
    },
    "roadmap",
    "changelog",
  ],
};

export default sidebars;