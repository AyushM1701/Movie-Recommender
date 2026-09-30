# CineMatch

CineMatch is a browser movie discovery and personal library application. Guests can search titles and themes, browse the published catalogue, find similar movies, and blend explicitly chosen movie and genre signals. Signed-in users save watched films, write optional ratings and notes, maintain a watchlist, and curate public or private lists.

Movie metadata and community ratings come from TMDB. Recommendation scores express model ordering and are not calibrated percentages or critic/personal ratings. Catalogue shelves use stored popularity and community ratings; they do not measure weekly user activity. Catalogue provenance reports the actual published cutoff and retrieval date when available.

Watch availability is regional, defaults to India (IN), and comes from TMDB with JustWatch attribution. Subscription, free, ads, rental, and purchase providers link to the returned HTTPS availability page. The application does not promise playback, invent provider deep links, or treat a temporary lookup failure as an empty regional listing.

The product operates on the existing Python API and vanilla JavaScript frontend. Personal collections and catalogue browsing are paginated. Owner access to private lists is distinct from public sharing. Browser sign-out removes this browser's credentials; changing a password or explicitly revoking sessions requires sign-in on all devices.

The interface supports keyboard use, clear loading/error/retry states, mobile navigation, meaningful labels, a topmost dialog stack, and reduced motion. Signup, saved genre preferences, browsing genres, and blend genres have independent selection state. Saved-history blending uses the bounded recent profile sample and shows its inputs; manual blending has its own visible film picker.
