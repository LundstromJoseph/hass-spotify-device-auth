# Spotify Device Auth

A Home Assistant custom integration that logs a Spotify account into a **Spotify
Connect speaker** over the local network (the Zeroconf username/password
"default" blob flow). Once logged in, the speaker shows up in the *regular*
Spotify app and can be targeted by the official `spotify` integration — no
SpotifyPlus, no Chromecast, no cloud round-trip.

This is the flow older speakers (Audio Pro, Bose, Onkyo, Yamaha, …) expect when
they advertise `tokenType=accesstoken`: the controller hands the device an
encrypted username/password blob, and the device logs itself into Spotify.

> **Note on passwords:** Spotify is deprecating password login. If you sign in
> with Google/Apple/Facebook, create a device password at
> <https://www.spotify.com/account/set-device-password/> and use that.

## Install (HACS)

1. HACS → ⋮ → **Custom repositories** → add
   `https://github.com/LundstromJoseph/hass-spotify-device-auth`, category
   **Integration**.
2. Install **Spotify Device Auth**, then restart Home Assistant.
3. Settings → Devices & Services → **Add Integration** → *Spotify Device Auth*,
   and enter:
   - **Name** – identifier you'll reference in scripts (e.g. `speaker`)
   - **Account id (loginId)** – your Spotify user ID

You can add multiple accounts; each becomes its own entry.

## Services

### `spotify_device_auth.login`
Logs an account into a speaker. Returns the device id (use it as the `source`
for `media_player.select_source`).

| Field | Required | Description |
|-------|----------|-------------|
| `host` | yes | Speaker IP/hostname |
| `account` | no | Account name; optional if only one is configured |
| `port` / `cpath` / `version` | no | Resolved via mDNS if omitted |

Response: `{ id, name, brand, model, result }`.

### `spotify_device_auth.logout`
Signs the current user out of a speaker (`resetUsers`).

### `spotify_device_auth.discover`
Returns Spotify Connect devices found on the LAN via mDNS.

## Example: play a playlist on the speaker

```yaml
sequence:
  - action: spotify_device_auth.login
    data:
      host: "10.0.0.130"
      account: "speaker"
    response_variable: login_result
  - action: media_player.select_source
    target:
      entity_id: media_player.spotify_joseph
    data:
      source: "{{ login_result.id }}"
  - action: media_player.play_media
    target:
      entity_id: media_player.spotify_joseph
    data:
      media_content_id: "spotify:playlist:645EgtEZm0oBAAaK8gz8XS"
      media_content_type: playlist
```

> The first login after a speaker has been idle can take 20–60s (mDNS + device
> wake); subsequent calls are fast.

## Credentials & backups

Credentials are stored in the integration's config entry (`.storage`), which is
included in Home Assistant backups. Use **encrypted backups** if that matters to
you.

## License

MIT
