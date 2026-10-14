"""Single definition of the season / episode model.

Season 1: episodes 1-4.   Season 2: episodes 5-8.   Season 3: planned, no episodes yet.

Everything that needs the mapping (assignments, statistics, export, tests) imports it from
here. Season 3 is deliberately *not* part of ACTIVE_EPISODES: it never contributes to a
completion percentage until real Season 3 work is introduced here on purpose.
"""

SEASONS = (
    {"n": 1, "status": "active", "episodes": (1, 2, 3, 4)},
    {"n": 2, "status": "active", "episodes": (5, 6, 7, 8)},
    {"n": 3, "status": "planned", "episodes": ()},
)

ACTIVE_EPISODES = tuple(ep for s in SEASONS if s["status"] == "active" for ep in s["episodes"])


def season_of(episode):
    """Season number of an episode, or None for an episode that is not part of the active scope."""
    for s in SEASONS:
        if episode in s["episodes"]:
            return s["n"]
    return None


def episodes_of(season):
    for s in SEASONS:
        if s["n"] == season:
            return s["episodes"]
    return ()


def is_active_episode(episode):
    return episode in ACTIVE_EPISODES
