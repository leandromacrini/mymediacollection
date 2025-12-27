import animeworld as aw
from dataclasses import dataclass

#aw.SES.base_url = "https://www.animeworld.so"

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

    

def find(title: str):
    result = aw.find(title)
    return result 

def search_animeworld_for_wanted(title: str):
    results = aw.find(title)
    return [AWMedia(id=r['id'], title=r['title'], link=r['link'], cover=r['cover'], episodes=r['episodes']) for r in results]

