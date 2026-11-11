# Discord Rich Presence

Mako ships with a ready-to-use Ocarina of Time Rich Presence by default. End users do not need to create a Discord application, edit an INI file, or upload artwork.

Built-in defaults:

- Application ID: `1569877496780947547`
- Details: `The Legend of Zelda: Ocarina of Time`
- State: `Exploring Hyrule`
- Large image key: `ocarina-title-new-960x540`
- Large image text: `The Legend of Zelda: Ocarina of Time`
- Small image key: `a59d076a-8dfa-4d04-8580-fb17ae4784df`
- Small image text: `Mako Emulator`
- Elapsed play time: automatic

The Discord Developer application must contain Rich Presence assets with the exact image keys above. The displayed `Playing <name>` label comes from that application's name in the Discord Developer Portal.

## Optional downstream overrides

Advanced users or downstream builds can still override any value in `hookshot_options.ini` without recompiling:

```ini
discord_app_id=1234567890123456789
discord_details=The Legend of Zelda: Ocarina of Time
discord_state=Exploring Hyrule
discord_large_image=ocarina-title-new-960x540
discord_large_text=The Legend of Zelda: Ocarina of Time
discord_small_image=mako
discord_small_text=Mako
```

`HOS_DISCORD_APP_ID` still overrides the application ID. The Insert menu's existing **Discord status** option still enables/disables the feature.
