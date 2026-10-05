# T8 Spec: React Front-End — Knowledge OS

## Objetivo

Criar **UI React moderna e responsiva** para acessar toda funcionalidade dos 38 tools MCP, instalada junto com o servidor.

## Inspiração + Identidade

### Referências (O que copiar/adaptar)
1. **Notion** — Workspace switcher, sidebar, rich editor
2. **Obsidian** — Knowledge graph, quick search, file explorer
3. **Supabase Studio** — Clean tables, forms, modal dialogs
4. **Logseq** — Dark mode, quick capture, linked references

### Identidade Visual (Nossa)
- **Cores:** 
  - Primary: `#3B82F6` (blue-500, confiável)
  - Secondary: `#8B5CF6` (purple-500, criatividade)
  - Accent: `#EC4899` (pink-500, insights)
  - Background: `#F8FAFC` (light), `#0F172A` (dark)
  - Border: `#E2E8F0` (light), `#1E293B` (dark)

- **Tipografia:**
  - Heading: Inter Bold (moderno)
  - Body: Inter Regular (limpo)
  - Mono: Fira Code (code snippets)

- **Logo:** "K" estilizado em gradiente blue→purple

---

## Stack Tecnológico

```json
{
  "frontend": {
    "framework": "React 18+",
    "language": "TypeScript",
    "styling": "Tailwind CSS",
    "components": "shadcn/ui + Radix UI",
    "state": "TanStack Query (data) + Zustand (UI)",
    "routing": "TanStack Router",
    "forms": "React Hook Form + Zod",
    "icons": "Lucide React",
    "rich-editor": "Tiptap (Markdown editor)",
    "date": "date-fns",
    "search": "Fuse.js (client-side FTS)",
    "build": "Vite",
    "deploy": "Vercel / Netlify"
  },
  "devDeps": {
    "testing": "Vitest + React Testing Library",
    "linting": "ESLint + Prettier",
    "bundler": "Vite",
    "type-checking": "TypeScript"
  },
  "api": {
    "client": "OpenAPI SDK (auto-generated)",
    "transport": "HTTP + JSON",
    "auth": "Bearer token (JWT simples)"
  }
}
```

---

## Arquitetura Frontend

```
web/
├── src/
│   ├── components/
│   │   ├── layout/
│   │   │   ├── Sidebar.tsx (workspace switcher, nav)
│   │   │   ├── Topbar.tsx (search, user menu)
│   │   │   └── Layout.tsx (shell)
│   │   ├── workspace/
│   │   │   ├── WorkspaceList.tsx (cards com ícones)
│   │   │   ├── WorkspaceDetail.tsx (domains list)
│   │   │   └── WorkspaceForm.tsx (create/edit)
│   │   ├── domain/
│   │   │   ├── DomainList.tsx (tabela + cards toggle)
│   │   │   ├── DomainDetail.tsx (items grid)
│   │   │   └── DomainForm.tsx (create/edit)
│   │   ├── item/
│   │   │   ├── ItemGrid.tsx (cards com preview)
│   │   │   ├── ItemTable.tsx (tabela interativa)
│   │   │   ├── ItemDetail.tsx (full page + relations graph)
│   │   │   ├── ItemEditor.tsx (Tiptap Markdown)
│   │   │   └── ItemForm.tsx (create/edit modal)
│   │   ├── search/
│   │   │   ├── GlobalSearch.tsx (cmd+k, FTS)
│   │   │   └── SearchResults.tsx (com highlights)
│   │   ├── relation/
│   │   │   ├── RelationGraph.tsx (Cytoscape.js)
│   │   │   └── RelationPanel.tsx (relações do item)
│   │   ├── ui/ (shadcn/ui imports)
│   │   │   ├── button.tsx
│   │   │   ├── dialog.tsx
│   │   │   ├── input.tsx
│   │   │   ├── card.tsx
│   │   │   ├── tabs.tsx
│   │   │   └── ... (20+ componentes)
│   │   └── common/
│   │       ├── Loading.tsx
│   │       ├── EmptyState.tsx
│   │       └── ErrorBoundary.tsx
│   ├── pages/
│   │   ├── Home.tsx (workspace grid)
│   │   ├── Workspace.tsx (domains list)
│   │   ├── Domain.tsx (items grid/table)
│   │   ├── Item.tsx (detail page)
│   │   └── NotFound.tsx
│   ├── hooks/
│   │   ├── useWorkspaces.ts (TanStack Query)
│   │   ├── useDomains.ts
│   │   ├── useItems.ts
│   │   ├── useSearch.ts
│   │   └── useAuth.ts
│   ├── lib/
│   │   ├── api.ts (OpenAPI client)
│   │   ├── utils.ts (formatters, helpers)
│   │   ├── constants.ts (colors, sizes)
│   │   └── cn.ts (clsx+tailwind)
│   ├── store/
│   │   ├── appStore.ts (Zustand: theme, sidebar)
│   │   └── authStore.ts (user, token)
│   ├── types/
│   │   ├── index.ts (types do API)
│   │   └── custom.ts (tipos locais)
│   ├── App.tsx
│   ├── main.tsx
│   └── index.css (Tailwind + custom)
├── public/
│   ├── logo.svg
│   ├── favicon.ico
│   └── screenshot.png
├── package.json
├── vite.config.ts
├── tsconfig.json
└── tailwind.config.js
```

---

## Páginas Principais

### 1. **Home** — Workspace Grid
```
┌─────────────────────────────────────┐
│ Knowledge OS    [+ New] [Settings]  │
├─────────────────────────────────────┤
│                                     │
│ ┌─────────────┐ ┌─────────────┐   │
│ │ BTG         │ │ Company     │   │
│ │ 3 domains   │ │ 5 domains   │   │
│ │ 42 items    │ │ 128 items   │   │
│ └─────────────┘ └─────────────┘   │
│                                     │
│ ┌─────────────┐ ┌─────────────┐   │
│ │ Personal    │ │ Archive     │   │
│ │ 2 domains   │ │ 12 domains  │   │
│ │ 24 items    │ │ 89 items    │   │
│ └─────────────┘ └─────────────┘   │
│                                     │
└─────────────────────────────────────┘
```

### 2. **Workspace Detail** — Domains List
```
┌────────────────────────────────────────┐
│ BTG / [+ New Domain] [Export] [Import] │
├────────────────────────────────────────┤
│                                        │
│ Domain              Items  Updated     │
│ ─────────────────────────────────────  │
│ ✓ Orquestra 2.0     12    5 min ago   │
│ ✓ OpenSearch        8     1 hour ago  │
│ ✓ Kubernetes        22    2 days ago  │
│ ⊙ Draft             0     never       │
│                                        │
└────────────────────────────────────────┘
```

### 3. **Domain Detail** — Items Grid/Table
```
[Grid View] [Table View] [+ New Item] [Search...]

Grid View:
┌────────┐ ┌────────┐ ┌────────┐
│ Title  │ │ Title  │ │ Title  │
│ Summ.. │ │ Summ.. │ │ Summ.. │
│🔗3 rel │ │🔗1 rel │ │🔗2 rel │
└────────┘ └────────┘ └────────┘

Table View:
Title               Type      Updated     Status
────────────────────────────────────────────────
ConditionalOnProp   Knowledge 5 min ago   ✓ Approved
Deploy Procedure    Procedure 1 h ago     ⏳ Pending
Java 21 Rule        Rule      2 d ago     ✓ Approved
```

### 4. **Item Detail** — Full Page
```
┌─────────────────────────────────┐
│ < Back    [Edit] [Delete] [...]  │
├─────────────────────────────────┤
│ Title: ConditionalOnProperty     │
│ Type: Knowledge | Class: longterm │
│ Tags: [spring] [java] [bean]     │
│ Labels: [official] [critical]    │
│ Confidence: ████████░ 90%        │
│ Importance: ██████░░░ 6/10       │
├─────────────────────────────────┤
│ Summary:                         │
│ Spring: @ConditionalOnProperty  │
│ avalia em startup, não runtime  │
├─────────────────────────────────┤
│ Content:                         │
│ [Markdown editor with preview]  │
│                                 │
│ A anotação @Conditional...     │
│ nunca permite dinâmico...      │
│                                 │
├─────────────────────────────────┤
│ Relations:                       │
│ → depends_on: Rule "Java 21"    │
│ ← related_to: Insight "..."     │
│                                 │
└─────────────────────────────────┘
```

### 5. **Global Search** (Cmd+K)
```
┌──────────────────────────────────┐
│ 🔍 Search across all workspaces..│
├──────────────────────────────────┤
│ 🔥 Recent                        │
│ • ConditionalOnProperty          │
│ • Deploy Procedure               │
│                                  │
│ 🌐 All Results (12)              │
│ > workspace: BTG                 │
│   • ConditionalOnProperty [95%]  │
│   • Deploy [87%]                 │
│ > workspace: Company             │
│   • Kubernetes [82%]             │
│                                  │
└──────────────────────────────────┘
```

---

## Componentes shadcn/ui Usados

```
✓ Button
✓ Input
✓ Dialog
✓ Tabs
✓ Card
✓ Badge
✓ Checkbox
✓ Radio
✓ Select
✓ Textarea
✓ Dropdown Menu
✓ Sheet (sidebar mobile)
✓ Toast (notifications)
✓ Loading Spinner
✓ Progress
✓ Tooltip
✓ Popover
✓ Command (palette)
✓ Separator
✓ Avatar
✓ Skeleton (loading states)
```

---

## Features Principais

### MVP (Sprint 1: 2-3 semanas)

**Tier 1: CRUD Básico**
- [ ] Workspace CRUD (create, read, update, delete)
- [ ] Domain CRUD
- [ ] Item CRUD (create, edit, delete)
- [ ] Connection CRUD (list, test)

**Tier 2: Search + Navigation**
- [ ] Global search (Cmd+K)
- [ ] Quick filters
- [ ] Breadcrumb navigation
- [ ] Sidebar active state

**Tier 3: Rich Editing**
- [ ] Markdown editor (Tiptap)
- [ ] Preview side-by-side
- [ ] Tags + Labels management
- [ ] Confidence/Importance sliders

**Tier 4: Polish**
- [ ] Dark mode toggle
- [ ] Loading states
- [ ] Error boundaries
- [ ] Empty states
- [ ] Mobile responsive

### v0.2+ (Future)

- Relation graph (Cytoscape.js)
- Export/Import UI
- User profiles + permissions
- Real-time collaboration (WebSocket)
- Infinite scroll
- Advanced filters
- Analytics dashboard

---

## Fluxo de Desenvolvimento

### Phase 1: Setup (1 dia)
```bash
npm create vite@latest web -- --template react-ts
cd web
npm install
  @tanstack/react-query
  @tanstack/react-router
  zustand
  react-hook-form
  zod
  tailwindcss
  shadcn/ui
  lucide-react
  @tiptap/react
  date-fns
  fuse.js
```

### Phase 2: Scaffolding (2-3 dias)
- Layout shell (Sidebar + Topbar + Main)
- Routing (Home → Workspace → Domain → Item)
- API client (OpenAPI SDK)
- Store (Zustand)

### Phase 3: CRUD Pages (5-7 dias)
- WorkspaceList, WorkspaceDetail, WorkspaceForm
- DomainList, DomainDetail, DomainForm
- ItemList, ItemDetail, ItemForm

### Phase 4: Search + Polish (3-5 dias)
- Global search (Cmd+K)
- Dark mode
- Loading/Error states
- Mobile responsive
- Performance optimization

### Phase 5: Testing + Deploy (2-3 dias)
- Vitest + RTL
- Responsive testing
- Deploy to Vercel/Netlify

**Total: 15-20 dias (3 semanas)**

---

## Integração com Backend

```typescript
// lib/api.ts
import { createClient } from "@openapi-ts/fetch-client";

const apiClient = createClient<{
  baseUrl: process.env.VITE_API_URL || "http://localhost:8000";
}>();

export const workspacesApi = {
  list: () => apiClient.GET("/api/workspaces"),
  create: (data) => apiClient.POST("/api/workspaces", data),
  get: (id) => apiClient.GET(`/api/workspaces/${id}`),
  update: (id, data) => apiClient.PUT(`/api/workspaces/${id}`, data),
  delete: (id) => apiClient.DELETE(`/api/workspaces/${id}`),
};

export const itemsApi = {
  search: (query, filters) => 
    apiClient.GET("/api/items/search", { query, ...filters }),
  create: (data) => apiClient.POST("/api/items", data),
  get: (id) => apiClient.GET(`/api/items/${id}`),
  update: (id, data) => apiClient.PUT(`/api/items/${id}`, data),
  delete: (id) => apiClient.DELETE(`/api/items/${id}`),
};
// ... etc
```

---

## Critério de Sucesso (T8)

✓ Setup Vite + React + TypeScript  
✓ shadcn/ui components working  
✓ 5+ páginas principal (Home, Workspace, Domain, Item, Search)  
✓ CRUD completo (create, read, update, delete)  
✓ Global search funcionando  
✓ Dark mode toggle  
✓ Mobile responsive (teste em iPhone)  
✓ 90%+ Lighthouse score  
✓ <3s initial load time  
✓ Deploy a Vercel/Netlify  
✓ Testes: 80%+ coverage (Vitest)  
✓ README com setup instructions  

---

## Deploy

### Local (Desenvolvimento)
```bash
cd web
npm run dev
# http://localhost:5173
```

### Production
```bash
npm run build
npm run preview

# Deploy via Vercel
npm install -g vercel
vercel
```

### Docker (com backend)
```dockerfile
# Dockerfile.web
FROM node:18-alpine AS build
WORKDIR /app
COPY web/ .
RUN npm install && npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
```

---

## Roadmap T8

- **Semana 1:** Setup + Scaffolding + CRUD básico
- **Semana 2:** Completa CRUD, Search, Dark mode
- **Semana 3:** Polish, testes, deploy

**Start:** Logo após T6 + T7 completarem (paralelo possível, depende de T6 estar 95% pronto)

**Entrega:** UI React funcional, responsiva, bonita, instalada junto com backend MCP

---

**Inspiração final:** 
- Notion: workspace switcher, sidebar
- Obsidian: quick search, dark mode
- Supabase: clean tables, modals
- Logseq: markdown editor, quick capture

**Identidade:** Blue + Purple gradient, Inter font, Dark mode first
