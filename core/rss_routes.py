"""Fixed production destinations with independent durable digest queues."""
from core.rss_preferences import tags
from features.news_channel_categories import CHANNELS

ROUTES = {
    'ps': ('PlayStation', CHANNELS['ps'], frozenset({'ps'})),
    'xbox': ('Xbox', CHANNELS['xbox'], frozenset({'xbox'})),
    'pc': ('PC', CHANNELS['pc'], frozenset({'4gamers'})),
}


class RouteConfig:
    def __init__(self, base, route):
        self.base = base
        self.route = route
        self.max_items = base.max_items
        self.offers = base.offers

    def score(self, article):
        if article['source'] not in ROUTES[self.route][2]:
            return None
        # Mixed 4Gamers articles need explicit PC/Steam/Epic evidence.
        if self.route == 'pc' and 'pc' not in tags(article)[0]:
            return None
        return self.base.score(article)
