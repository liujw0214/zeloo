# Zeloo Agent — Documentación del Desarrollador

> **Zeloo** — El agente que crece contigo.
> Un framework de runtime de agente AI auto-hospedado y auto-evolutivo.

## Características Principales

- **Auto-evolutivo**: Aprende de cada sesión y mejora con el tiempo
- **Multi-plataforma**: Conecta a Telegram, Discord, Slack, WeChat Work, DingTalk, Feishu y más
- **Memoria persistente**: Almacena contexto a través de sesiones
- **Skills progresivos**: Desarrolla y refina habilidades automáticamente
- **Arquitectura extensible**: Plugins, MCP, y herramientas personalizadas

## Inicio Rápido

```bash
# Clonar repositorio
git clone <Zeloo-repo-url>
cd Zeloo

# Instalar con uv
uv venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
uv pip install -e .

# Configurar variables de entorno
cp .env.example .env
# Editar .env con tu API Key

# Iniciar CLI
Zeloo

# Comandos comunes
Zeloo config show     # Ver configuración
Zeloo doctor          # Diagnóstico
Zeloo sessions        # Listar sesiones
Zeloo skills          # Listar skills
```

## Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│                    Interfaz de Usuario                       │
│     CLI / TUI / Gateway (Telegram/Discord/etc.)           │
├─────────────────────────────────────────────────────────────┤
│                    Núcleo del Agente                        │
│  System Prompt (3 capas) │ Loop de Conversación │ Tools   │
├─────────────────────────────────────────────────────────────┤
│                    Capas de Capacidad                       │
│  Skills │ Memoria │ Cron │ Subagente │ MCP │ i18n        │
├─────────────────────────────────────────────────────────────┤
│                    Infraestructura                           │
│  SQLite(WAL+FTS5) │ 7 Backends │ Multi-Provider          │
└─────────────────────────────────────────────────────────────┘
```

## Sistema de Prompts de 3 Capas

| Capa | Nombre | Contenido | Caché |
|------|--------|-----------|-------|
| Stable | Estable | Identidad, guía de herramientas | Prefix cache permanente |
| Context | Contexto | Archivos de proyecto, platform_hint | Por proyecto |
| Volatile | Variable | Índice de skills, snapshot de memoria | Cada turno |

## Stack Tecnológico

| Categoría | Tecnología |
|-----------|------------|
| Lenguaje principal | Python 3.11+ |
| Gestión de paquetes | uv |
| Base de datos | SQLite (WAL + FTS5) |
| Frontend | Node.js 22+ / pnpm |
| LLM | OpenAI-compatible, 30+ providers |

## Desarrollo

```bash
# Ejecutar tests
python -m pytest tests/ -v

# Linting
uv run ruff check .

# Agregar nueva herramienta
# Editar tools/registry.py y crear tools/my_tool.py
```

## Contribuir

Ver [CONTRIBUTING.md](./CONTRIBUTING.md) para guías de desarrollo.

## Licencia

MIT — ver [LICENSE](./LICENSE)
