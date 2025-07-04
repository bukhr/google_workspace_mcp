# Servidor MCP de Google Workspace

Este es un servidor Model Context Protocol (MCP) para interactuar con Google Workspace.

## Requisitos previos

- Python 3.11+
- uv (para ejecución local)
- Un proyecto de Google Cloud con credenciales Oauth 2.0

## Configuración

### 1. Setup Proyecto de Google Cloud

#### 1.1 Crea un nuevo proyecto de Google Cloud

#### 1.2 Habilita las APIs de Google Drive y Docs

#### 1.3 Crea credenciales OAuth 2.0 y Configura las URIs de Redirección

#### 1.4 Descarga el archivo `client_secret.json`

### 2. Configurar Codeium MCP

- Añade la siguiente configuración a tu archivo de configuración de Codeium MCP (`~/.codeium/windsurf/mcp_config.json`):

```json
   {
     "mcpServers": {
       "google_workspace": {
        "command": "uv",
        "args": [
          "--directory",
          "path/to/google_workspace_mcp",
          "run",
          "main.py",
          "--tools",
          "docs"
        ],
        "env": {
          "OAUTHLIB_INSECURE_TRANSPORT": "1",
          "WORKSPACE_MCP_BASE_URI": "http://localhost",
          "WORKSPACE_MCP_PORT": "8080"
        }
      }
     }
   }
```

Para el nombre de usuario, normalmente es tu correo corporativo.

En `path/to/google_workspace_mcp` reemplaza `path/to` con la ruta absoluta en tu máquina al repo.

## Uso

El servidor MCP será iniciado automáticamente por Codeium cuando sea necesario. Herramientas disponibles:

- `start_google_auth`: Iniciar el proceso de autenticación con Google

## Hacer pruebas

Recomendamos probar haciendole preguntas.

Algunos prompts de prueba:

## Ejemplos de Uso

### Discovery Técnico de Misiones

### Resumen de documentos de Tracks

## Para más información

Referenciar la [documentación del servidor original](https://github.com/taylorwilsdon/google_workspace_mcp?tab=readme-ov-file#google-workspace-mcp-server-)

Y cualquier duda la pueden hacer llegar en el canal @coord-guild-prod-windsurf. También queda abierto a contribuciones para ir mejorando cada vez más la experiencia y los casos de uso!
