# beets-youtube
A plugin for [beets](https://github.com/beetbox/beets) to use YouTube as a metadata source.

## Installation

Install the plugin using `pip`:

```shell
pip install git+https://github.com/arsaboo/beets-youtube.git
```

Then, [configure](#configuration) the plugin in your
[`config.yaml`](https://beets.readthedocs.io/en/latest/plugins/index.html) file.

## Configuration

Add `YouTube` to your list of enabled plugins.

```yaml
plugins: youtube
```

This plugin relies on OAuth authentication as detailed [here](https://ytmusicapi.readthedocs.io/en/stable/setup/oauth.html) and expects the oauth.json file in the beets config folder. The easiest way to make it work is to generate the oauth.json outside the plugin and just paste the json file in the beets folder. You can configure fields to be excluded from being updated using the following config (only these fields can be excluded):
```yaml
youtube:
    exclude_fields:
        - cover_art_url
```

## Features

The following features are implemented in `youtube`:

* `beet ytupdate`: allows you to get the current view count of the videos.
