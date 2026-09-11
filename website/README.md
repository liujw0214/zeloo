# Zeloo Documentation Site

This directory contains the Docusaurus-based documentation site for Zeloo.

## Local development

```bash
cd website
npm install
npm start
```

Open <http://localhost:3000> in your browser.

## Build for production

```bash
npm run build
npm run serve
```

## Structure

```
website/
├── docs/                 # Documentation markdown files
│   ├── intro.md
│   ├── getting-started/
│   ├── architecture/
│   └── modules/
├── src/                  # Custom React components (add when needed)
├── static/               # Static assets (images, favicons)
├── docusaurus.config.ts  # Site configuration
├── sidebars.ts           # Sidebar structure
└── package.json
```

## Adding a new page

1. Create a new `.md` file in `docs/` with frontmatter:

   ```yaml
   ---
   id: my-page
   title: My Page
   sidebar_label: My Page
   ---
   ```

2. Register it in `sidebars.ts` under the appropriate category.

3. Restart the dev server.