import animeworld as aw
from dataclasses import dataclass
from typing import List, Optional
from core import db_core

#aw.SES.base_url = "https://www.animeworld.so"

downloads_in_progress: 'List[AWDownload]' = []

@dataclass
class AWMedia:
    def __init__(self, raw: dict):
        self.source = "animeworld"

        self.source_id = raw["id"]
        self.link = raw["link"]

        self.title = raw["name"]
        self.original_title = raw.get("jtitle")
        self.year = int(raw["year"]) if raw.get("year") else None
        self.episodes = raw.get("episodes")

        self.description = raw.get("story")
        self.cover = raw.get("image")

        self.studio = raw.get("studio")
        self.season = raw.get("season")
        self.language = raw.get("language")
        self.dub = raw.get("dub")

        self.duration = raw["durationEpisodes"] if raw.get("durationEpisodes") else None

        self.mal_id = raw.get("malId")
        self.anilist_id = raw.get("anilistId")
        self.mal_vote = raw.get("malVote")

        self.categories = raw.get("categories", [])

        self.status = "new"

    

@dataclass
class AWDownload:
    media: AWMedia
    episode_number: int
    status: str  # queued, downloading, completed

def download_wanted(media_link: str, episodes: List[int]):
    anime = aw.Anime(media_link)
    eps = anime.getEpisodes(episodes)
    downloads = []
    for ep in eps:
        ep.download()
        downloads.append(AWDownload(media=media_link, episode_number=ep.number, status="queued"))
    return downloads

def get_queue():
    return downloads_in_progress  # può essere aggiornato ogni volta che l'utente lancia un download

def get_animeworld_status_map(db: db_core.MediaDB) -> dict:
    media_status_list= db.getMediaStatus('animeworld')
    return {str(ms.external_id): ms.status for ms in media_status_list}


def find(title: str):
    return aw.find(title)

def search_animeworld_for_wanted(title: str):
    results = aw.find(title)
    return [AWMedia(id=r['id'], title=r['title'], link=r['link'], cover=r['cover'], episodes=r['episodes']) for r in results]

