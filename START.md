# 🚀 Knowledge OS — Quick Start

## Instalação

```bash
cd /c/Projects/second-brain-mcp-server

# Via pip
pip install fastapi uvicorn sqlalchemy pydantic

# OU via uv
uv sync
```

## Rodando

### **UI (Dashboard)**
```bash
knowledge-mcp ui --port 9876
```
✅ Abrir: **http://127.0.0.1:9876/ui/** (sem login; a UI só escuta em 127.0.0.1).

### **MCP (Standalone)**
```bash
python src/main.py
```
Expõe 40 tools via FastMCP protocol (stdio)

---

## **Recurso Estático: UI**

A UI está servida como **resource estático** em:
- **Rota:** `/ui/` (raiz: `/ui/index.html`)
- **Tecnologia:** Alpine.js + ES modules + CSS próprio (libs via CDN, sem build)
- **Funcionalidades:**
  - Dashboard workspaces
  - Criar/listar domains
  - Criar/listar items com search
  - FTS search across all workspaces
  - Persistência via localStorage

---

## **API Endpoints**

Acesso via HTTP (porta 9876):

```
GET    /           → Health check
GET    /api/workspaces
POST   /api/workspaces
GET    /api/domains
POST   /api/domains
GET    /api/items
POST   /api/items
GET    /api/items/search
```

---

## **Base de Dados**

- **Default:** SQLite local (`./knowledge.db`)
- **Conexões:** Configuradas em `.knowledge/connections.json`
- **Schema:** Auto-sincronizado via `schema_sync`

---

## **MCP Tools (40)**

Via `python src/main.py`:

```
Connection (6 CRUD + 2 utilities)
Workspace (5)
Domain (4)
Item (7 + search)
Relation (3)
Tag/Label (6)
Artifact (3)
Memory (2)
Health (1)
```

Veja `src/mcp/INSTRUCTIONS.md` para detalhes.

---

## **Troubleshooting**

| Problema | Solução |
|----------|---------|
| Porta 9876 em uso | Mudar `--port` para outra |
| "No module fastapi" | `pip install fastapi uvicorn sqlalchemy` |
| Database vazio | `python src/main.py` inicia schema automaticamente |
| Cache corrompido | `pip cache purge` ou `rm -rf .venv && python -m venv .venv` |

---

**Pronto para usar!** 🎉
