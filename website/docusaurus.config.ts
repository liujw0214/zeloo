import { themes as prismThemes } from "prism-react-renderer";
import type { Config } from "@docusaurus/types";
import type * as Preset from "@docusaurus/preset-classic";

const config: Config = {
  title: "Zeloo",
  tagline: "A self-hosted, self-evolving AI agent runtime",
  favicon: "img/favicon.ico",

  url: "https://Zeloo.dev",
  baseUrl: "/",

  organizationName: "Zeloo",
  projectName: "Zeloo",

  onBrokenLinks: "throw",
  onBrokenMarkdownLinks: "warn",

  i18n: {
    defaultLocale: "en",
    locales: ["en", "zh"],
  },

  presets: [
    [
      "classic",
      {
        docs: {
          sidebarPath: "./sidebars.ts",
          routeBasePath: "/",
          showLastUpdateTime: true,
        },
        blog: false,
        theme: {
          image: "img/social-card.png",
        },
        sitemap: {
          changefreq: "weekly",
          priority: 0.5,
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    image: "img/social-card.png",
    colorMode: {
      defaultMode: "dark",
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: "Zeloo",
      logo: {
        alt: "Zeloo Logo",
        src: "img/logo.svg",
      },
      items: [
        {
          type: "docSidebar",
          sidebarId: "ZelooSidebar",
          position: "left",
          label: "Docs",
        },
        {
          href: "https://github.com/Zeloo/Zeloo",
          label: "GitHub",
          position: "right",
        },
      ],
    },
    footer: {
      style: "dark",
      links: [
        {
          title: "Docs",
          items: [
            { label: "Getting Started", to: "/docs/intro" },
            { label: "Architecture", to: "/docs/architecture" },
            { label: "Roadmap", to: "/docs/roadmap" },
          ],
        },
        {
          title: "Community",
          items: [
            { label: "GitHub", href: "https://github.com/Zeloo/Zeloo" },
            { label: "Discord", href: "https://discord.gg/Zeloo" },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} Zeloo Project.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
    algolia: {
      appId: "PLACEHOLDER",
      apiKey: "PLACEHOLDER",
      indexName: "Zeloo",
    },
  } satisfies Preset.ThemeConfig,
};

export default config;