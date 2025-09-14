# beets-youtube Plugin

beets-youtube is a Python plugin for the [beets](https://github.com/beetbox/beets) music library that uses YouTube as a metadata source and allows updating view counts for tracks.

**Always reference these instructions first and fallback to search or bash commands only when you encounter unexpected information that does not match the info here.**

## Working Effectively

### Bootstrap and Install
- Install the plugin in development mode:
  - `cd /home/runner/work/beets-youtube/beets-youtube`
  - `pip3 install -e . --user` -- takes ~2 seconds. NEVER CANCEL.
- Verify installation: `beet version` should show beets version and Python version.

### Core Dependencies
- **Python 3.12+** required
- **beets 2.4.0+** - Music library management system  
- **ytmusicapi 1.11.1+** - YouTube Music API wrapper
- **Pillow** - Image processing
- **requests** - HTTP library

### OAuth Setup (Required for Full Functionality)
- The plugin requires OAuth authentication with YouTube Music API
- **CRITICAL**: You MUST have a valid `oauth.json` file in your beets config directory to use the plugin
- Follow [ytmusicapi OAuth setup](https://ytmusicapi.readthedocs.io/en/stable/setup/oauth.html) to generate `oauth.json`
- Without OAuth credentials, the plugin will fail to load with `YTMusicUserError`

### Configuration
Create a beets config file (`config.yaml`) with:
```yaml
plugins: youtube

youtube:
    exclude_fields:
        - cover_art_url
    source_weight: 0.5
```

### Testing Plugin Import and Syntax
- Test basic import: `python3 -c "from beetsplug.youtube import extend_reimport_fresh_fields_item; print('Import successful')"`
- Check syntax validity: `python3 -c "import ast; ast.parse(open('beetsplug/youtube.py').read()); print('Syntax valid')"`
- **NOTE**: Full plugin functionality requires OAuth setup, but syntax and imports can be tested without it.

## Validation

### Manual Testing Steps
1. **ALWAYS** run installation and import tests after making code changes
2. **CRITICAL**: Test plugin loading with beets: `BEETSDIR=/path/to/test/config beet version`
3. If OAuth is configured, test the `ytupdate` command: `beet ytupdate`
4. Validate that syntax changes don't break Python imports

### Common Issues and Troubleshooting
- **Import errors**: The plugin was updated for beets 2.4.0+ compatibility. Key fixes:
  - `Distance` imports from `beets.autotag.distance` not `beets.autotag.hooks`  
  - `distance` function imports from `beets.autotag.distance` not `beets.plugins`
- **OAuth errors**: Plugin requires valid YouTube Music OAuth credentials in `oauth.json`
- **Plugin load failures**: Check beets config syntax and ensure all dependencies are installed

### Build and Test Commands
- **Install dependencies**: `pip3 install -e . --user` -- 2 seconds, NEVER CANCEL
- **Syntax check**: `python3 -c "import ast; ast.parse(open('beetsplug/youtube.py').read())"`
- **Import test**: `python3 -c "from beetsplug.youtube import YouTubePlugin"`
- **Plugin load test**: `BEETSDIR=/tmp/test beet version` (requires config file and oauth.json)

### Linting and Code Quality
- **No built-in linters**: Repository does not include flake8, pylint, or other linting tools
- **Manual validation**: Always check Python syntax with `ast.parse()` after changes
- **Follow Python conventions**: Maintain consistent code style with existing codebase

## Common Tasks

### Repository Structure
```
/home/runner/work/beets-youtube/beets-youtube/
├── README.md                 # Plugin documentation and usage
├── setup.py                  # Installation configuration
├── beetsplug/               
│   ├── __init__.py          # Package init (2 lines)
│   └── youtube.py           # Main plugin implementation (350+ lines)
├── LICENSE                  # MIT license
└── .gitignore               # Standard Python gitignore
```

### Key Files and Functions
- **beetsplug/youtube.py**: Main plugin with these key functions:
  - `YouTubePlugin.__init__()`: Plugin initialization and OAuth setup
  - `get_albums()`: Search for album metadata
  - `get_tracks()`: Search for track metadata  
  - `_ytupdate()`: Update view counts for tracks
  - `import_youtube_playlist()`: Import YouTube playlist
  - `get_yt_views()`: Get view count for YouTube videos

### Plugin Features
- **Metadata source**: Use YouTube as source for track/album metadata
- **View count updates**: `beet ytupdate` command to refresh YouTube view counts
- **OAuth authentication**: Supports YouTube Music API authentication
- **Configurable exclusions**: Can exclude specific fields from updates
- **Playlist import**: Import tracks from YouTube playlists

### Dependencies in setup.py
```python
install_requires=[
    'beets>=1.6.0',      # Music library system
    'ytmusicapi>=1.10.2', # YouTube Music API
    'requests',          # HTTP requests
    'pillow',           # Image processing
]
```

### Development Workflow
1. Make code changes in `beetsplug/youtube.py`
2. Test syntax: `python3 -c "import ast; ast.parse(open('beetsplug/youtube.py').read())"`
3. Test import: `python3 -c "from beetsplug.youtube import YouTubePlugin"`  
4. Reinstall: `pip3 install -e . --user`
5. Test with beets: `BEETSDIR=/path/to/config beet version`

### Timing Expectations
- **Installation**: ~2 seconds
- **Import/syntax tests**: <1 second  
- **Plugin loading**: <1 second (with valid OAuth)
- **Metadata searches**: Variable, depends on network and YouTube API response

**NEVER CANCEL** any operation unless it exceeds these expected times by 5x or more.