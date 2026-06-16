"""Constants for the Spotify Device Auth integration."""

DOMAIN = "spotify_device_auth"

# Config entry data keys (CONF_NAME/USERNAME/PASSWORD come from homeassistant.const)
CONF_ACCOUNT_ID = "account_id"

# Service names + field keys
SERVICE_LOGIN = "login"
SERVICE_LOGOUT = "logout"
SERVICE_DISCOVER = "discover"

CONF_ACCOUNT = "account"
CONF_CPATH = "cpath"
CONF_VERSION = "version"
CONF_TIMEOUT = "timeout"

DEFAULT_VERSION = "1.0"
DEFAULT_DISCOVERY_TIMEOUT = 5.0

SPOTIFY_CONNECT_TYPE = "_spotify-connect._tcp.local."
