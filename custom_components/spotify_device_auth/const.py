"""Constants for the Spotify Device Auth integration."""

DOMAIN = "spotify_device_auth"

# Config entry data keys (CONF_NAME/USERNAME/PASSWORD come from homeassistant.const)
CONF_ACCOUNT_ID = "account_id"

# Service names + field keys
SERVICE_LOGIN = "login"
SERVICE_LOGOUT = "logout"
SERVICE_DISCOVER = "discover"
SERVICE_PLAY = "play"

CONF_ACCOUNT = "account"
CONF_CPATH = "cpath"
CONF_VERSION = "version"
CONF_TIMEOUT = "timeout"
CONF_DEVICE_ID = "device_id"
CONF_CONTEXT_URI = "context_uri"
CONF_URIS = "uris"

DEFAULT_VERSION = "1.0"
DEFAULT_DISCOVERY_TIMEOUT = 5.0

SPOTIFY_CONNECT_TYPE = "_spotify-connect._tcp.local."

# Core Spotify integration we borrow the OAuth token from
SPOTIFY_DOMAIN = "spotify"
SPOTIFY_PLAY_URL = "https://api.spotify.com/v1/me/player/play"
# How long to keep retrying while a freshly logged-in device registers with Spotify
PLAY_RETRY_ATTEMPTS = 5
PLAY_RETRY_DELAY = 1.5
