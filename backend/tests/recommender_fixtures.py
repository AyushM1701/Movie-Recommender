"""Small deterministic catalog fixtures independent of generated models and TMDB."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

from backend.recommender import RecommendationEngine


class OfflinePosters:
    def resolve(self, movie_id: int) -> str:
        return ""

    def close(self) -> None:
        pass


def make_engine() -> RecommendationEngine:
    entries = [
        (
            27205,
            "Inception",
            ["Science Fiction", "Thriller"],
            "dream subconscious shared dream theft layered reality time travel",
            ["dream", "heist"],
        ),
        (
            1002,
            "Dream Thief",
            ["Science Fiction", "Thriller"],
            "shared dream subconscious theft layered reality heist time travel",
            ["dream", "heist"],
        ),
        (
            157336,
            "Interstellar",
            ["Science Fiction", "Adventure"],
            "astronaut space exploration wormhole gravity father rescue daughter",
            ["space", "family"],
        ),
        (
            1004,
            "Red Moon",
            ["Science Fiction", "Adventure"],
            "astronaut space exploration mars stranded rescue survival",
            ["space", "survival"],
        ),
        (
            238,
            "The Godfather",
            ["Drama", "Crime"],
            "mafia patriarch crime family gangster loyalty father succession",
            ["mafia", "family"],
        ),
        (
            240,
            "The Godfather Part II",
            ["Drama", "Crime"],
            "mafia patriarch crime family gangster loyalty succession betrayal",
            ["mafia", "family"],
        ),
        (
            155,
            "The Dark Knight",
            ["Action", "Crime", "Thriller"],
            "batman superhero joker gotham vigilante crime dark knight",
            ["batman", "superhero"],
        ),
        (
            272,
            "Batman Begins",
            ["Action", "Crime"],
            "batman superhero gotham vigilante crime dark knight origins",
            ["batman", "superhero"],
        ),
        (
            862,
            "Toy Story",
            ["Animation", "Family", "Comedy"],
            "toys friendship cowboy astronaut adventure children woody buzz",
            ["toys", "friendship"],
        ),
        (
            863,
            "Toy Story 2",
            ["Animation", "Family", "Comedy"],
            "toys friendship cowboy astronaut adventure rescue woody buzz",
            ["toys", "friendship"],
        ),
        (
            19995,
            "Avatar",
            ["Action", "Adventure", "Fantasy", "Science Fiction"],
            "alien planet forest human invasion ecology soldier pandora",
            ["alien", "forest"],
        ),
        (
            1012,
            "Silent Streets",
            ["Drama", "Comedy"],
            "silent comedy city tramp friendship poverty work",
            ["silent", "poverty"],
        ),
    ]
    rows = []
    for index, (movie_id, title, genres, overview, keywords) in enumerate(entries):
        rows.append(
            {
                "id": movie_id,
                "title": title,
                "genres_list": genres,
                "overview": overview,
                "keywords_list": keywords,
                "vote_average": 8.7 if index == 0 else 7.5,
                "vote_count": 2000 if index == 0 else 500,
                "popularity": 90.0 if index == 0 else 20.0,
                "release_date": "1921-01-01" if index == 11 else "2010-01-01",
                "status": "Released",
                "runtime": 120,
                "poster_path": "",
                "cast_list": [],
                "director_list": [],
                "tags": overview + " " + " ".join(genres),
            }
        )
    engine = RecommendationEngine.__new__(RecommendationEngine)
    engine.movies = pd.DataFrame(rows)
    engine.indices = pd.Series(engine.movies.index, index=engine.movies.title)
    engine.id_to_index = pd.Series(engine.movies.index, index=engine.movies.id)
    engine.tfidf_vectorizer = TfidfVectorizer(dtype=np.float32)
    engine.tfidf_matrix = engine.tfidf_vectorizer.fit_transform(engine.movies.tags).tocsr()
    engine.tfidf_bundle = None
    engine.semantic_embeddings = None
    engine.semantic_reducer = None
    engine.semantic_info = {}
    engine._semantic_query_model = None
    engine._genre_lookup = {}
    engine._catalog_stats = {}
    engine.poster_repository = OfflinePosters()
    engine.catalog_repository = None
    engine._prepare_indexes()
    return engine


class FixtureCatalog:
    """The API suite uses the same canonical test titles without accessing disk."""

    def __init__(self, *args, **kwargs) -> None:
        self.engine = make_engine()

    def get_movie(self, movie_id: int) -> dict | None:
        return self.engine.get_movie_by_id(movie_id)

    def stats(self) -> dict:
        return self.engine.get_catalog_stats()

    def metadata(self) -> dict:
        return {"cutoff": "2026-09-30", "source": "offline_test_fixture"}

    def search_titles(self, query: str, limit: int = 12) -> list[dict]:
        return [
            self.engine._format_movie(row)
            for _, row in self.engine.movies.iterrows()
            if query.casefold() in row["title"].casefold()
        ][:limit]

    def browse(
        self, page=1, page_size=24, genre=None, year_from=None, year_to=None, sort="popular", min_rating=0
    ) -> dict:
        import math

        movies = [self.engine._format_movie(row) for _, row in self.engine.movies.iterrows()]
        movies = [movie for movie in movies if movie["vote_average"] >= min_rating]
        if genre:
            movies = [movie for movie in movies if genre in movie["genres"]]
        if year_from is not None:
            movies = [movie for movie in movies if int(movie["release_year"]) >= year_from]
        if year_to is not None:
            movies = [movie for movie in movies if int(movie["release_year"]) <= year_to]
        return {
            "movies": movies[(page - 1) * page_size : page * page_size],
            "total": len(movies),
            "page": page,
            "page_size": page_size,
            "pages": math.ceil(len(movies) / page_size),
        }
