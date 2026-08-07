# Changelog

All notable changes to DockedUp will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-08-07

### Added
- **Filter/search**: Press `/` to filter the container list by container or project name
- **Project mode**: Press `p` to select a whole Compose project and restart or stop every container in it at once
- **Container detail view**: Press `i` to see image, command, entrypoint, mounts, networks and restart policy for the selected container

### Changed
- **Command execution**: Interactive commands (`logs -f`, `exec -it`) now run through `subprocess` instead of `os.system`

## [1.0.2] - 2026-04-18

### Fixed
- **Remote Docker connection support**: Fixed critical issue where only a few containers would show when using SSH remote connections (`DOCKER_HOST=ssh://user@hostname`)
- **IncompleteRead errors**: Eliminated `IncompleteRead` network errors that caused containers to disappear from the monitor
- **Container visibility**: Containers now remain visible even when stats collection fails due to network issues

### Changed
- **Stats collection mode**: Remote connections (SSH/TCP) now use polling mode instead of streaming for better reliability
- **Error handling**: Network errors no longer remove containers; stats are gracefully disabled with "—" indicator
- **Retry logic**: Added exponential backoff retry mechanism (up to 3 retries for remote connections)
- **Connection timeout**: Increased Docker connection timeout from 5s to 10s for better remote connection support

### Added
- **`--no-stats` flag**: New CLI option to completely disable stats collection (useful for slow remote connections)
- **Auto-detection**: Automatic detection of remote Docker connections with optimized behavior
- **Debug messages**: Better logging for remote connection detection in debug mode

## [1.0.1] - 2026-04-XX

### Added
- PageUp/PageDown navigation for scrolling through projects
- Improved viewport handling for large numbers of projects

### Changed
- Updated README with clearer installation instructions
- Improved demo GIF in documentation

## [1.0.0] - 2026-04-XX

### Added
- Initial release
- Real-time Docker container monitoring
- Interactive TUI with keyboard controls
- Docker Compose project grouping
- Container actions (logs, restart, stop, shell)
- CPU and memory usage tracking
- Health check status display
- Color-coded status indicators
