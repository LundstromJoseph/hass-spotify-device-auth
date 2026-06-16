# Spotify Device Auth

Log a Spotify account into a **Spotify Connect speaker** over your LAN (Zeroconf
username/password "default" blob flow), so the speaker appears in the regular
Spotify app and can be targeted by the official `spotify` integration.

Provides three services:

- `spotify_device_auth.login` – log an account into a speaker; returns the
  device id (use as the `source` for `media_player.select_source`)
- `spotify_device_auth.logout` – sign out (`resetUsers`)
- `spotify_device_auth.discover` – list Spotify Connect devices on the LAN

Configure one or more accounts from the UI (name, username, password, account
id). See the [README](https://github.com/LundstromJoseph/hass-spotify-device-auth)
for an example playlist-on-speaker script.
