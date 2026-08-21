from asyncio import threads
from datetime import datetime
import json
import os
import sys
import threading
import time
from argparse import Namespace
from dataclasses import asdict, dataclass
from glob import glob
from typing import Any
from urllib.parse import urljoin
from urllib.parse import urlparse


import requests
from bs4 import BeautifulSoup, Tag
from colorama import Fore
from langdetect import detect as detect_lang
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium_stealth import stealth
from seleniumwire import webdriver
from yt_dlp import YoutubeDL

from tools.functions import get_confirmation, get_int_in_range, safe_remove, vtt_to_srt
# from tools.YTDLogger import YTDLogger


@dataclass
class Anime:
    name: str
    url: str                # anime page URL (e.g., /anime/xxx)
    watch_url: str          # watch episode URL (e.g., /watch/xxx/ep-1)
    sub_episodes: int
    dub_episodes: int
    # download_type can be "sub", "dub"
    download_type: str = ""
    season_number: int = -1
    episode_offset: int = 0
    year: int | None = None

class SilentLogger:
    def debug(self, msg):
        pass
    def warning(self, msg):
        pass
    def error(self, msg):
        pass
    def info(self, msg):
        pass

class HianimeExtractor:
    def __init__(self, args: Namespace, name: str | None = None) -> None:
        self.args: Namespace = args

        self.link = self.args.link
        self.name = name

        self.HEADERS: dict[str, str] = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.11 (KHTML, like Gecko) Chrome/23.0.1271.64 Safari/537.11",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Charset": "ISO-8859-1,utf-8;q=0.7,*;q=0.3",
            "Accept-Encoding": "none",
            "Accept-Language": "en-US,en;q=0.8",
            "Connection": "keep-alive",
        }
        self.URL: str = "https://hianimez.org/"
        self.ENCODING = "utf-8"
        self.SUBTITLE_LANG: str = "en"
        self.OTHER_LANGS: list[str] = [
            "ita",
            "jpn",
            "pol",
            "por",
            "ara",
            "chi",
            "cze",
            "dan",
            "dut",
            "fin",
            "fre",
            "ger",
            "gre",
            "heb",
            "hun",
            "ind",
            "kor",
            "nob",
            "pol",
            "rum",
            "rus",
            "tha",
            "vie",
            "swe",
            "spa",
            "tur",
            "ces",
            "bul",
            "zho",
            "nld",
            "fra",
            "deu",
            "ell",
            "hin",
            "hrv",
            "msa",
            "may",
            "ron",
            "slk",
            "slo",
            "ukr",
        ]
        self.DOWNLOAD_REFRESH: tuple[int, int, int] = (7, 22, 37)
        self.SERVER_REFRESH: tuple[int, int, int] = (15, 30, 44, 52)
        self.BAD_TITLE_CHARS: list[str] = [
            "-",
            ".",
            "/",
            "\\",
            "?",
            "%",
            "*",
            "<",
            ">",
            "|",
            '"',
            "[",
            "]",
            ":",
        ]
        self.TITLE_TRANS: dict[int, Any] = str.maketrans(
            "", "", "".join(self.BAD_TITLE_CHARS)
        )

        self.download_progress = {}  # Maps episode name to progress info (ETA)
        self._progress_lock = threading.Lock()

    def run(self):
        # Determine how to get the Anime object:
        if self.link:
            # If a direct link is provided, fetch anime from the link
            anime: Anime | None = self.get_anime_from_link(self.link)
        elif self.name:
            # If a name is provided, search for the anime by name
            anime: Anime | None = self.get_anime(self.name)
        else:
            # Otherwise, prompt the user to enter the anime name
            anime: Anime | None = self.get_anime()

        if not anime:
            return

        # Display chosen anime details
        print(
            Fore.LIGHTGREEN_EX
            + "\nYou have chosen "
            + Fore.LIGHTBLUE_EX
            + anime.name
            + Fore.LIGHTGREEN_EX
            + f"\nURL: {Fore.LIGHTBLUE_EX}{anime.url}{Fore.LIGHTGREEN_EX}"
            + Fore.LIGHTGREEN_EX
            + f"\nWatch URL: {Fore.LIGHTBLUE_EX}{anime.watch_url}{Fore.LIGHTGREEN_EX}"
            + "\nSub Episodes: "
            + Fore.LIGHTYELLOW_EX
            + str(anime.sub_episodes)
            + Fore.LIGHTGREEN_EX
            + "\nDub Episodes: "
            + Fore.LIGHTYELLOW_EX
            + str(anime.dub_episodes)
            + Fore.LIGHTCYAN_EX
        )

        # Determine download type based on availability and default preference
        if anime.sub_episodes != 0 and anime.dub_episodes != 0:
            # Both available - use default if set and valid, otherwise ask
            if self.args.default_download_type and self.args.default_download_type.lower() in ["sub", "dub"]:
                print(f"Using default download type of {self.args.default_download_type.lower()}.")
                anime.download_type = self.args.default_download_type.lower()
            else:
                anime.download_type = self.get_download_type()
        elif anime.dub_episodes == 0:
            print("Dub episodes are not available. Defaulting to sub.")
            anime.download_type = "sub"
        else:
            print("Sub episodes are not available. Defaulting to dub.")
            anime.download_type = "dub"
        
        # if dub is chosen, ask if subtitles are wanted
        if anime.download_type == "dub" and self.args.subtitles:
            self.args.subtitles = input(f"{Fore.LIGHTCYAN_EX}Do you want to download subtitles for the dub? (y/n):{Fore.LIGHTYELLOW_EX} ").strip().lower() == "y"

        number_of_episodes = getattr(anime, f"{anime.download_type}_episodes")
        if number_of_episodes != 1 and not self.args.download_all:
            start_ep = get_int_in_range(
                f"{Fore.LIGHTCYAN_EX}Enter the starting episode number (inclusive, default=1):{Fore.LIGHTYELLOW_EX} ",
                1,
                number_of_episodes, 
                1
            )
            end_ep = get_int_in_range(
                f"{Fore.LIGHTCYAN_EX}Enter the ending episode number (inclusive, default={number_of_episodes}):{Fore.LIGHTYELLOW_EX} ",
                1,
                number_of_episodes, 
                number_of_episodes
            )
        else:
            start_ep = 1
            end_ep = number_of_episodes

        if self.args.is_ova:
            anime.season_number = 0
            anime.episode_offset = get_int_in_range(
                f"{Fore.LIGHTCYAN_EX}Enter the OVA episode number offset for filename use (default=0):{Fore.LIGHTYELLOW_EX} ",
                0,
                10000, 0
            )

        if self.args.is_movie:
            anime.year = self.get_anime_year(anime.name)
            if not anime.year:
                anime.year = get_int_in_range(
                    f"{Fore.LIGHTCYAN_EX}Enter the movie release year (e.g., {datetime.datetime.now().year}):{Fore.LIGHTYELLOW_EX} ",
                    datetime.datetime.now().year - 150,
                    datetime.datetime.now().year + 1,
                    datetime.datetime.now().year
                )
            anime.name += f" ({anime.year})"

        if anime.season_number == -1 and not self.args.is_movie and not self.args.is_ova:
            # only ask for season number if not already set (OVA is set to 0)
            # and if not a movie (movies don't have seasons)
            anime.season_number = get_int_in_range(
                f"{Fore.LIGHTCYAN_EX}Enter the season number for this anime:{Fore.LIGHTYELLOW_EX} "
            )

        print(Fore.LIGHTGREEN_EX + f"\nCreating folder for {anime.name} if does not exist...\n")

        folder = self.create_anime_folder(anime)

        if self.args.json_file:
            print(Fore.LIGHTGREEN_EX + f"Downloading episodes {start_ep} - {end_ep} from {self.args.json_file}\n")
            self.download_from_json(anime, self.args.json_file, folder, start_ep, end_ep)
            return

        self.configure_driver()
        self.driver.get(anime.watch_url)

        button: WebElement = self.find_server_button(anime)  # type: ignore

        # Toggle the quick-settings before selecting server
        self.toggle_auto_play()

        try:
            button.click()
        except Exception as e:
            print(
                f"{Fore.LIGHTRED_EX}Error clicking server button:\n\n{Fore.LIGHTWHITE_EX}{e}"
            )

        episode_list: list[dict] = self.get_episode_urls(
            self.driver.page_source, start_ep, end_ep
        )

        print()

        self.captured_video_urls = []
        self.captured_subtitle_urls = []
        threads = []
        for episode in episode_list:
            url = episode["url"]
            number = episode["number"]
            title = episode["title"]

            print(
                Fore.LIGHTGREEN_EX
                + "Getting"
                + Fore.LIGHTWHITE_EX
                + f" Episode {number} - {title} from {url}"
                + Fore.LIGHTWHITE_EX
            )

            try:
                self.driver.requests.clear()
                self.driver.get(url)
                self.driver.execute_script("window.focus();")
                media_requests = self.capture_media_requests(anime)
                if not media_requests:
                    print("No m3u8 file was found skipping download")
                    continue
                
                episode.update(media_requests)
                self.captured_video_urls.append(media_requests["m3u8"])
                if self.args.subtitles:
                    self.captured_subtitle_urls.append(media_requests["vtt"])

                # Have episode URL now, so kick off thread to download it
                t = threading.Thread(target=self.download_episode, args=(anime, episode, folder), daemon=True)
                t.start()
                threads.append(t)
            except KeyboardInterrupt:
                print("\n\nCanceling media capture...")
                if not get_confirmation(
                    "Would you like to download link capture up to now? (y/n): "
                ):
                    self.driver.quit()
                    return

        self.driver.quit()
        print()

        print(f"\n{Fore.LIGHTGREEN_EX}Waiting for all downloads to complete...\n")
        while threads:
            max_eta = 0
            with self._progress_lock:
                for ep_name, prog in self.download_progress.items():
                    eta = prog.get("eta")
                    if eta is not None:
                        max_eta = max(max_eta, eta)
            for t in threads[:]:
                if not t.is_alive():
                    t.join()
                    threads.remove(t)
            alive_count = len(threads)
            eta_min = int(max_eta // 60)
            eta_sec = int(max_eta % 60)
            eta_str = f"{eta_min}m {eta_sec}s"
            print(f"{Fore.LIGHTCYAN_EX}Downloads in progress: {alive_count}, Max Episode ETA: {eta_str}".ljust(80), end="\r")
            if alive_count == 0:
                break
            time.sleep(10)
        print(f"\n\n{Fore.LIGHTGREEN_EX}All downloads completed!\n")
        
        self.write_anime_json(folder, anime, episode_list)


    #function to create anime folder for storing downloads
    def create_anime_folder(self, anime: Anime) -> str:
        # Only include download type in folder name if it differs from default
        type_suffix = ""
        if self.args.default_download_type:
            if anime.download_type.lower() != self.args.default_download_type.lower():
                type_suffix = f" ({anime.download_type[0].upper()}{anime.download_type[1:]})"
        else:
            # If no default is set, always include the type
            type_suffix = f" ({anime.download_type[0].upper()}{anime.download_type[1:]})"
        
        folder = (
            os.path.abspath(self.args.output_dir)
            + os.sep
            + anime.name
            + type_suffix
            + os.sep
        )
        os.makedirs(folder, exist_ok=True)
        return folder
    

    #function to write anime and episodes data to a json file
    def write_anime_json(self, folder: str, anime: Anime, episodes: list[dict[str,Any]]) -> None:
        """Write anime and episodes data to a JSON file."""
        with open(
            f"{folder}{anime.name} (Season {anime.season_number}).json", "w"
        ) as json_file:
            json.dump({**asdict(anime), "episodes": episodes}, json_file, indent=4)


    #download episodes from a json file
    def download_from_json(self, anime: Anime, json_file: str, folder: str, start_ep: int, end_ep: int) -> None:
        """Download episodes from a JSON file containing episode data."""
        with open(f"{folder}{json_file}", "r") as file:
            episodes = json.load(file)["episodes"]

        threads = []
        for episode in episodes:
            if episode["number"] < start_ep or episode["number"] > end_ep:
                continue
            print(f"\nDownloading Episode {episode['number']} - {episode['title']}")

            t = threading.Thread(target=self.download_episode, args=(anime, episode, folder), daemon=True)
            t.start()
            threads.append(t)

        print(f"\n{Fore.LIGHTGREEN_EX}Waiting for all downloads to complete...\n")
        while threads:
            max_eta = 0
            with self._progress_lock:
                for ep_name, prog in self.download_progress.items():
                    eta = prog.get("eta")
                    if eta is not None:
                        max_eta = max(max_eta, eta)
            for t in threads[:]:
                if not t.is_alive():
                    t.join()
                    threads.remove(t)
            alive_count = len(threads)
            eta_min = int(max_eta // 60)
            eta_sec = int(max_eta % 60)
            eta_str = f"{eta_min}m {eta_sec}s"
            print(f"{Fore.LIGHTCYAN_EX}Download threads still running: {alive_count}, Max Episode ETA: {eta_str}".ljust(80), end="\r")
            if alive_count == 0:
                break
            time.sleep(10)
        print(f"\n\n{Fore.LIGHTGREEN_EX}All downloads completed!\n")



    #function to download a single episode, used in a thread
    def download_episode(self, anime: Anime, episode: dict[str, Any], folder: str) -> None:

        # episode titles may have bad characters so we need to sanitize them
        title = episode["title"].translate(self.TITLE_TRANS)
        if self.args.is_movie:
            name = f"{title} (Movie)"
        elif self.args.is_ova:
            # OVA tends to be special episodes outside of the main season, so using season 0
            name = f"s{anime.season_number:02}e{(episode['number'])+anime.episode_offset:02} - {title} (OVA)"
        else:
            name = f"s{anime.season_number:02}e{episode['number']:02} - {title}"
        if "m3u8" not in episode.keys() and not episode["m3u8"]:
            print(f"Skipping {name} (No M3U8 Stream Found)")
            return

        try:
            result = self.yt_dlp_download(
                self.look_for_variants(episode["m3u8"], episode["headers"]),
                episode["headers"],
                f"{folder}{name}.mp4",
                episode_name=name
            )
        except Exception as e:
            print(f"\n\n{Fore.LIGHTRED_EX}Error while downloading {name}: \n\n{e}")
            return
        
        if not result:
            print(f"Failed to download {name}, skipping subtitles if any")
            return

        if "vtt" in episode.keys() and episode["vtt"]:
            vtt_path = f"{folder}{name}.vtt"
            self.yt_dlp_download(
                episode["vtt"], episode["headers"], vtt_path
            )
            
            # Convert to SRT if requested
            if self.args.srt_format:
                try:
                    srt_path = vtt_to_srt(vtt_path)
                    safe_remove(vtt_path)  # Remove VTT file after conversion
                    print(f"{Fore.LIGHTGREEN_EX}Converted to {os.path.basename(srt_path)}")
                except Exception as e:
                    print(f"{Fore.LIGHTRED_EX}Error converting {name}.vtt to SRT: {e}")
        elif self.args.subtitles:
            print(f"Skipping {name}.vtt (No VTT Stream Found)")


    @staticmethod
    def get_download_type():
        ans = (
            input(
                f"\n{Fore.LIGHTCYAN_EX}Both sub and dub episodes are available. Do you want to download sub or dub? (Enter 'sub' or 'dub'):{Fore.LIGHTYELLOW_EX} "
            )
            .strip()
            .lower()
        )
        if ans == "sub" or ans == "s":
            return "sub"
        elif ans == "dub" or ans == "d":
            return "dub"
        print(
            f"{Fore.LIGHTRED_EX}Invalid response, please respond with either 'sub' or 'dub'."
        )
        return HianimeExtractor.get_download_type()

    def toggle_auto_play(self) -> None:
        """Toggle the quick-settings toggle to enable auto_play."""
        try:
            # 1. Locate the interactive toggle element based on your HTML structure
            autoplay_toggle = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "div.toggle-basic[data-name='auto_play']"))
            )

            # Configuration for the retry loop
            max_attempts = 5
            attempt = 0
            success = False

            # Track the base page window handle
            main_window = self.driver.current_window_handle

            while attempt < max_attempts and not success:
                attempt += 1
                print(f"Attempt {attempt}: Trying to toggle Auto Play...")
                
                # 1. Trigger the JavaScript click
                self.driver.execute_script("arguments[0].click();", autoplay_toggle)
                time.sleep(0.5)  # Wait for the browser to register the click and potential popup
        
                # 2. Immediately hunt and destroy any popups spawned by this click
                if len(self.driver.window_handles) > 1:
                    print(f"-> Popup detected on attempt {attempt}. Cleaning up...")
                    for handle in self.driver.window_handles:
                        if handle != main_window:
                            self.driver.switch_to.window(handle)
                            self.driver.close()
                    # Refocus back to the main site window
                    self.driver.switch_to.window(main_window)
                    time.sleep(0.5)  # Let the DOM settle after switching back
                    
                # 3. Check if the element state actually changed to 'on'
                current_classes = autoplay_toggle.get_attribute("class")
                if "on" in current_classes.split():
                    print(f"Success! Auto Play turned ON on attempt {attempt}.")
                    success = True
                    time.sleep(2)
                else:
                    print(f"-> Attempt {attempt} failed to update state (ad overlay likely swallowed the click).")

            if not success:
                print("Failed to turn Auto Play on after maximum attempts.")

        except Exception as e:
            print(f"An error occurred: {e}")
    
    def get_anime_year(self, title: str) -> str | None:
        """Look up the release year of an anime/movie using Jikan (MyAnimeList) API."""
        url = f"https://api.jikan.moe/v4/anime"
        params = {"q": title, "limit": 1}
        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            results = data.get("data", [])
            if results:
                aired_from = results[0].get("aired", {}).get("from")
                if aired_from:
                    year = aired_from[:4]
                    return year
                else:
                    print("No air date found for this anime.")
            else:
                print("Anime not found.")
        else:
            print("Error contacting Jikan API.")
        return None

    def configure_driver(self) -> None:
        mobile_emulation: dict[str, str] = {"deviceName": "iPhone X"}

        options: webdriver.ChromeOptions = webdriver.ChromeOptions()

        # Create a temporary user data dir
        # user_data_dir = tempfile.mkdtemp()
        # options.add_argument(f"--user-data-dir={user_data_dir}")

        options.add_experimental_option("mobileEmulation", mobile_emulation)
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("window-size=600,1000")

        # options.add_argument("--disable-popup-blocking")
        options.add_experimental_option(
            "prefs",
            {
                "profile.default_content_setting_values.notifications": 2,  # Block notifications
                "profile.default_content_setting_values.popups": 2,  # Block pop-ups
                "profile.managed_default_content_settings.ads": 2,  # Block ads
            },
        )
        options.add_argument("--disable-features=PopupBlocking")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-backgrounding-occluded-windows")
        # options.add_argument("--load-extension=extensions" + os.sep + )

        options.add_argument("--disable-gpu")
        options.add_argument("--log-level=3")
        options.add_argument("--silent")
        options.add_experimental_option("excludeSwitches", ["enable-logging"])

        seleniumwire_options: dict[str, bool] = {
            "verify_ssl": False,
            "disable_encoding": True,
        }

        self.driver: webdriver.Chrome = webdriver.Chrome(
            options=options,
            seleniumwire_options=seleniumwire_options,
        )

        stealth(
            self.driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )

        self.driver.implicitly_wait(10)

        self.driver.execute_script(
            """
                window.alert = function() {};
                window.confirm = function() { return true; };
                window.prompt = function() { return null; };
                window.open = function() {
                    console.log("Blocked a popup attempt.");
                    return null;
                };
            """
        )

    def get_server_options(self, download_type: str) -> list[WebElement]:
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "servers-content"))
        )

        servers_container = self.driver.find_element(By.ID, "servers-content")
    
        # Find all anchor elements within servers-content
        all_servers = servers_container.find_elements(By.TAG_NAME, "a")
        
        # Filter by data-type attribute
        if download_type in ["sub", "s"]:
            servers = [s for s in all_servers if s.get_attribute("data-type") == "sub"]
        else:
            servers = [s for s in all_servers if s.get_attribute("data-type") == "dub"]
        
        # Debug: print what we found
        # print(f"Found {len(servers)} servers for {download_type}")
        # for i, server in enumerate(servers):
        #     print(f"Server {i}: {server.text} (data-type: {server.get_attribute('data-type')})")
    
        return servers


    def find_server_button(self, anime: Anime) -> WebElement | None:
        options = self.get_server_options(anime.download_type)
        selection = None

        # Try command line server argument first
        if self.args.server:
            for option in options:
                if option.text.lower().strip() == self.args.server.lower().strip():
                    selection = option.text

        # Try default_server list from config if no selection yet
        if not selection and hasattr(self.args, 'default_server') and self.args.default_server:
            # Handle both string and list formats
            default_servers = self.args.default_server if isinstance(self.args.default_server, list) else [self.args.default_server]
            for default_srv in default_servers:
                for option in options:
                    if option.text.lower().strip() == default_srv.lower().strip():
                        selection = option.text
                        break
                if selection:
                    break

        if not selection:
            if self.args.server:
                print(
                    f"{Fore.LIGHTGREEN_EX}The server name you provided does not exist\n"
                )
            print(
                f"\n{Fore.LIGHTGREEN_EX}Select the server you want to download from: \n"
            )

            server_names = []
            for i, option in enumerate(options):
                server_names.append(option.text)
                print(f"{Fore.LIGHTRED_EX} {i + 1}: {Fore.LIGHTCYAN_EX}{option.text}")

            self.driver.requests.clear()
            self.driver.quit()

            selection = server_names[
                get_int_in_range(
                    f"\n{Fore.LIGHTCYAN_EX}Server (default=1):{Fore.LIGHTYELLOW_EX} ",
                    1,
                    len(options),
                    1
                )
                - 1
            ]
        else:
            self.driver.requests.clear()
            self.driver.quit()

        print(f"\n{Fore.LIGHTGREEN_EX}You chose: {Fore.LIGHTCYAN_EX}{selection}")

        self.configure_driver()
        self.driver.get(anime.watch_url)

        options = self.get_server_options(anime.download_type)

        for option in options:
            if option.text == selection:
                return option

        print(f"{Fore.LIGHTRED_EX}No matching server button could be found")
        return None
    
    def click_server_button(self, anime: Anime) -> None:
        print(f"{Fore.LIGHTRED_EX}\nClicking server button...")
        options = self.get_server_options(anime.download_type)
        selection = self.args.server

        for option in options:
            if option.text == selection:
                button: WebElement = option
                try:
                    button.click()
                except Exception as e:
                    print(
                        f"{Fore.LIGHTRED_EX}Error clicking server button:\n\n{Fore.LIGHTWHITE_EX}{e}"
                    )
                    input("Please manually click the button and then press Enter to continue...")
  

    def get_episode_urls(
        self, page: str, start_episode: int, end_episode: int
    ) -> list[dict[str, Any]]:
        episodes: list[dict[str, Any]] = []
        soup = BeautifulSoup(page, "html.parser")

        links: list[Tag] = soup.find_all("a", attrs={"data-num": True})  # type: ignore

        for link in links:
            episode_number: int = int(str(link.get("data-num")))
            if start_episode <= episode_number <= end_episode:
                url = urljoin(self.URL, str(link["href"]))
                episode_title = link.get("title")
                episode_info = {
                    "url": url,
                    "number": int(episode_number),
                    "title": episode_title,
                }
                episodes.append(episode_info)
        return episodes

    def capture_media_requests(self, anime: Anime) -> dict[str, str] | None:
        found_m3u8: bool = False
        found_vtt: bool = not self.args.subtitles
        attempt: int = 0
        urls: dict[str, Any] = {"all-vtt": []}
        previously_found_vtt: int = 0

        all_urls = []
        while (
            not found_m3u8 or not found_vtt
        ) and self.args.max_retries >= attempt:
            sys.stdout.write(
                f"\r{Fore.CYAN}Attempt #{attempt} - {self.args.max_retries - attempt} Attempts Remaining"
            )
            sys.stdout.flush()

            for request in self.driver.requests:
                if not request.response:
                    continue

                uri = request.url.lower()
                if uri not in all_urls:
                    all_urls.append(uri)
                if (
                    not found_m3u8
                    and uri.endswith(".m3u8")
                    and "master" in uri
                    and uri not in self.captured_video_urls
                ):
                    urls["m3u8"] = uri
                    urls["headers"] = dict(request.headers)
                    found_m3u8 = True
                    continue
                if (
                    not found_vtt
                    and ".vtt" in uri
                    and "thumbnail" not in uri
                    and uri not in self.captured_subtitle_urls
                    and not any(lang in uri for lang in self.OTHER_LANGS)
                    and detect_lang(
                        requests.get(uri, headers=dict(request.headers)).content.decode(
                            self.ENCODING
                        )
                    )
                    == self.SUBTITLE_LANG
                ):
                    if uri in urls["all-vtt"]:
                        previously_found_vtt += 1
                        if previously_found_vtt >= len(urls["all-vtt"]):
                            found_vtt = True
                        continue

                    urls["all-vtt"].append(uri)
            attempt += 1
            if attempt in self.SERVER_REFRESH:
                self.click_server_button(anime)
            if attempt in self.DOWNLOAD_REFRESH:
                print(f"\n{Fore.LIGHTRED_EX}Attempting page refresh..")
                self.driver.refresh()
            time.sleep(1)

        print()
        if not found_m3u8:
            print(f"{Fore.LIGHTRED_EX}No .m3u8 streams found.")
            return None
        if not found_vtt:
            print(
                f"\n{Fore.LIGHTRED_EX}No .vtt streams found. Check that the subtitles are not apart of the video file, option '--subtitles' can be used to enable downloading subtitles."
            )
            self.args.subtitles = not get_confirmation(
                f"\n{Fore.LIGHTCYAN_EX}Would you like to skip the collection of subtitles on the following episodes (y/n): "
            )
            print()
        elif self.args.subtitles:
            if len(urls["all-vtt"]) == 1:
                urls["vtt"] = urls["all-vtt"][0]
                return urls

            print(
                "\nMore than one subtitle file was found plesae select the on you would like to download:\n"
            )
            for i, vtt in enumerate(urls["all-vtt"]):
                print(f" {i + 1} - {vtt}")

            selection = get_int_in_range(
                "\nSelected Subtitle: ", 1, len(urls["all-vtt"]) + 1
            )
            print()

            urls["vtt"] = urls["all-vtt"][selection - 1]

        return urls

    @staticmethod
    def look_for_variants(m3u8_url: str, m3u8_headers: dict[str, Any]) -> str:
        response = requests.get(m3u8_url, headers=m3u8_headers)
        lines = response.text.splitlines()
        url = None
        for line in lines:
            if line.strip().endswith(".m3u8") and "iframe" not in line:
                url = urljoin(m3u8_url, line.strip())
                break
        if not url:
            print("No valid video variant found in master.m3u8")
            return ""

        return url

    def yt_dlp_download(self, url: str, headers: dict[str, str], location: str, episode_name: str = "") -> bool:
        def progress_hook(d):
            if d['status'] == 'downloading':
                with self._progress_lock:
                    self.download_progress[episode_name] = {
                        "eta": d.get("eta", None)
                    }
            elif d['status'] == 'finished':
                with self._progress_lock:
                    self.download_progress[episode_name] = {
                        "done": True
                    }

        yt_dlp_options: dict[str, Any] = {
            "no_warnings": False,
            "quiet": True,
            "outtmpl": location,
            "format": "best",
            "http_headers": headers,
            "logger": SilentLogger(),
            "fragment_retries": 10,
            "retries": 10,
            "socket_timeout": 60,
            "sleep_interval_requests": 1,
            "force_keyframes_at_cuts": True,
            "allow_unplayable_formats": True,
            "progress_hooks": [progress_hook],
        }

        _return = True
        with YoutubeDL(yt_dlp_options) as ydl:
            try:
                ydl.download([url])
            except KeyboardInterrupt:
                print(
                    f"\n\n{Fore.LIGHTCYAN_EX}Canceling Downloads...\nRemoving Temp Files for {location[location.rfind(os.sep) + 1:-4]}"
                )
                _return = False
                ydl.close()

        if not _return:
            for file in [
                f
                for f in glob(location[:-4] + ".*")
                if not f.endswith((".mp4", ".vtt"))
            ]:
                safe_remove(file)

        return _return

    def get_anime(self, name: str | None = None) -> Anime | None:
        os.system("cls" if os.name == "nt" else "clear")
        print(Fore.LIGHTGREEN_EX + "\nHiAnime " + Fore.LIGHTWHITE_EX + "GDown\n")

        search_name: str = name if name else input("Enter Name of Anime: ")

        # GET ANIME ELEMENTS FROM PAGE
        url: str = urljoin(self.URL, "/search?keyword=" + search_name)
        search_page_response: requests.Response = requests.get(
            url, headers=self.HEADERS
        )
        search_page_soup: BeautifulSoup = BeautifulSoup(
            search_page_response.content, "html.parser"
        )

        main_content: Tag = search_page_soup.find("div", id="main-content")  # type: ignore
        anime_elements: list[Tag] = main_content.find_all("div", class_="flw-item")  # type: ignore

        if not anime_elements:
            print("No anime found")
            return  # Exit if no anime is found

        # MAKE DICT WITH ANIME TITLES
        anime_list: list[Anime] = []
        for i, element in enumerate(anime_elements, 1):
            raw_name: str = element.find("h3", class_="film-name").text  # type: ignore
            name_of_anime: str = raw_name.translate(self.TITLE_TRANS)
            url_of_anime: str = urljoin(
                self.URL,
                str(element.find("a", class_="film-poster-ahref item-qtip")["href"]),  # type: ignore
            )

            try:
                # Some anime has no subs
                sub_episodes_available: int = element.find(
                    "div", class_="tick-item tick-sub"
                ).text  # type: ignore
            except AttributeError:
                sub_episodes_available: int = 0
            try:
                dub_episodes_available: int = element.find(
                    "div", class_="tick-item tick-dub"
                ).text  # type: ignore
            except AttributeError:
                dub_episodes_available: int = 0

            anime_list.append(
                Anime(
                    name_of_anime,
                    url_of_anime,
                    int(sub_episodes_available),
                    int(dub_episodes_available),
                )
            )

        # PRINT ANIME TITLES TO THE CONSOLE
        for i, anime in enumerate(anime_list, start=1):
            print(
                " "
                + Fore.LIGHTRED_EX
                + str(i)
                + ": "
                + Fore.LIGHTCYAN_EX
                + anime.name
                + Fore.WHITE
                + " | "
                + "Episodes: "
                + Fore.LIGHTYELLOW_EX
                + str(anime.sub_episodes)
                + Fore.LIGHTWHITE_EX
                + " sub"
                + Fore.LIGHTGREEN_EX
                + " / "
                + Fore.LIGHTYELLOW_EX
                + str(anime.dub_episodes)
                + Fore.LIGHTWHITE_EX
                + " dub"
            )

        # USER SELECTS ANIME
        return anime_list[
            get_int_in_range(
                f"\n{Fore.LIGHTCYAN_EX}Select an anime you want to download:{Fore.LIGHTYELLOW_EX} ",
                1,
                len(anime_list) + 1,
            )
            - 1
        ]

    def get_anime_from_link(self, link: str) -> Anime:
        link_page: requests.Response = requests.get(link, headers=self.HEADERS)
        link_page_soup = BeautifulSoup(link_page.content, "html.parser")
        main_div: Tag = link_page_soup.find("div", "anisc-detail")  # type: ignore
        anime_stats: Tag = main_div.find("div", "film-stats")  # type: ignore

        try:
            # Some anime has no subs
            sub_episodes_available: int = int(
                anime_stats.find("div", class_="tick-item tick-sub").text  # type: ignore
            )
        except AttributeError:
            sub_episodes_available: int = 0
        try:
            dub_episodes_available: int = int(
                anime_stats.find("div", class_="tick-item tick-dub").text  # type: ignore
            )
        except AttributeError:
            dub_episodes_available: int = 0

        try:
            a_tag: Tag = main_div.find("h2", "film-name").find("a")  # type: ignore
            anime_href = str(a_tag["href"]).strip()
            
            # Handle both absolute URLs and relative paths
            if anime_href.startswith("http"):
                # If href is already a full URL, extract the path
                parsed = urlparse(anime_href)
                anime_path = parsed.path
            else:
                anime_path = anime_href

            # anime_path starts with /watch or /anime, so split and create two paths
            parts = anime_path.split("/")
            if len(parts) >= 3:
                # Extract the anime ID/name from watch path
                anime_id = parts[2]  # e.g., "the-ramparts-of-ice-dxyxt"
                anime_path = f"/anime/{anime_id}"
                watch_path = f"/watch/{anime_id}"
            
            anime_url = urljoin(self.URL, anime_path)
            watch_url = urljoin(self.URL, watch_path)

            return Anime(
                str(a_tag.text).translate(self.TITLE_TRANS),
                anime_url,
                watch_url,
                sub_episodes_available,
                dub_episodes_available,
            )
        except:
            print(f"\n\n{Fore.LIGHTRED_EX}URL not valid, provide the 'watch' URL")
            return


