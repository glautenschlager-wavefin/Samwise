# Samwise
My faithful coding assistant, from green fields to Mount Doom

## Setup

### Python Backend
```bash
make install
```

### VS Code Extension
```bash
make ext-install
make ext-build
```

To develop the extension:
1. `make ext-install` to install dependencies
2. Press **F5** to launch the Extension Development Host
3. The Samwise sidebar, status bar, and `@samwise` chat participant will be active

Or run `make ext-watch` for continuous rebuilds during development.

### Running the Backend
Set your GitHub credentials, then start the server:
```bash
export SAMWISE_GITHUB_TOKEN=ghp_your_token_here
export SAMWISE_GITHUB_USERNAME=your_username
make serve
```

The backend runs at `http://127.0.0.1:9474`. The extension auto-connects to it and falls back to mock data if unavailable.

**Environment variables:**
| Variable | Description | Default |
|---|---|---|
| `SAMWISE_GITHUB_TOKEN` | GitHub personal access token | *(required for live data)* |
| `SAMWISE_GITHUB_USERNAME` | Your GitHub username | *(required for live data)* |
| `SAMWISE_HOST` | Server bind address | `127.0.0.1` |
| `SAMWISE_PORT` | Server port | `9474` |
| `SAMWISE_POLL_INTERVAL_SECONDS` | How often to poll GitHub | `120` |
