# HiAnimez Downloader

- Threading to allow concurrent episode downloads
- Config file to specify defaults and minimize user input
- Error handling to prevent program crashes

This command-line tool searches HiAnimez and downloads episodes, movies, and OVAs. It is focused exclusively on HiAnimez; links from other services are not supported.


## Requirements

- Python3 + PIP3
- Chrome Installed

## Setup

1. Download the files from the repository.

2. Navigate into the directory it was downloaded to in your terminal.
3. Using pip install all the requirement from the `requirements.txt` file.
   - For Windows

     ```bash
      pip install -r requirements.txt
     ```

   - For Linux/macOS you may have to first create a virtual environment, so use the following commands.

     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     python3 -m pip install -r requirements.txt
     ```

4. You are now ready to run the program with the following command.
   - Windows

     ```bash
      python main.py
     ```

   - Linux/MacOS

     ```bash
      python3 main.py
     ```

## Usage

- After running `main.py`, enter an anime name to search HiAnime or provide a HiAnime link.

- If you enter a name of an anime it will bring up a selection of anime options from the site, select the desired one with the corresponding number.

- Follow the prompts to choose sub or dub, episode range, and streaming server.

<!-- - **Note** if a redirect ad to a second tab is created, close the second tab manually and refresh the original site to
  continue download. (This will hopefully be patched eventually) -->



## Options

You are able to pass parameters when running the file to add additional options.

- `-o` or `--output-dir` lets you provide a path for the output files. For example,

  ```bash
  python3 main.py -o ~/Movies/
  ```

- `-l` or `--link` allows you to pass in a HiAnime link

- `-n` or `--filename` allows you to pass in the anime name to search for

- `--no-subtitles` downloads the content without looking for subtitle files

- `--server` allows you to select the streaming server you would like to download from.

  - NOTE: Vidstream and Vidplay tend to work better

### Usage Example

```bash
python3 main.py -o ~/Desktop/ --server "HD-1" -n "Solo Leveling" --no-subtitles

```

## Default Configuration

You can customize default behaviors by editing the `config.json` file. This allows you to avoid repetitive prompts and streamline your downloads. Here are the available configuration options:

### Configuration Options

- **`default_server`**: Set a list of preferred streaming servers in priority order. The tool will try each server in sequence until it finds an available one. If none are available, you'll be prompted to choose.
  - Example: `"default_server": ["Vidstream-2","HD-1", "HD-2"]`
  - Set to `null` or `[]` to always prompt for server selection

- **`default_download_type`**: Set your preferred download type (`"sub"` or `"dub"`). When both are available, this choice will be used automatically. If only one type is available, that one will be used regardless of this setting.
  - Example: `"default_download_type": "dub"`
  - Set to `null` to always prompt when both sub and dub are available

- **`download_all`**: When set to `true`, automatically downloads all episodes without prompting for a range.
  - Example: `"download_all": true`
  - Default: `false`

- **`subtitles`**: When set to `true`, downloads subtitle files (.vtt or .srt) along with the video.
  - Default: `true`

- **`srt_format`**: When set to `true`, converts downloaded .vtt subtitle files to .srt format.
  - Default: `false`

- **`output_dir`**, **`movie_output_dir`**, **`ova_output_dir`**: Customize the default output directories for different content types.

### Example Configuration

```json
{
  "subtitles": true,
  "output_dir": "/Users/yourname/Anime",
  "movie_output_dir": "/Users/yourname/Movies",
  "ova_output_dir": "/Users/yourname/OVAs",
  "default_server": ["Vidstream-1", "HD-1", "HD-2"],
  "default_download_type": "dub",
  "download_all": true,
  "srt_format": false
}
```

With this configuration, the tool will:
- Automatically use dub when available
- Try Vidstream-2 first, then HD-1, then HD-2 for streaming
- Download all episodes without asking for a range
- Save files to your specified directories
- Download subtitles in .vtt format

**Note**: Folder naming automatically adapts to your `default_download_type`. If you set `"dub"` as default, dub folders won't have "(Dub)" appended to their names. Sub folders will still show "(Sub)" to distinguish them.


#todo:
- Sub, HSUB, and DUB options
- Eventually, allow hsub but that seems like multiple changes needed
- Only works with "watch" links, not "anime" links
