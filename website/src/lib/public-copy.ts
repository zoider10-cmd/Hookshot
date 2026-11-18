// Neutral public wording for imported menu help and repository activity. Source records, links and runtime
// identifiers remain intact; this changes only descriptive text published by the website.

/** The game's names the published site must not show; scripts/check-site.ts rejects a build that still has one. */
export const GAME_BRANDING = /\b(?:Nintendo|Zelda|Ocarina|OoT|Hyrule|Kokiri|Kakariko|Deku|Goron|Zora|Ganon|Ganondorf|Epona|Triforce|Navi)\b|\bSwitch 2\b|\bJoy-Cons?\b/i;
const ANY_GAME_BRANDING = new RegExp(GAME_BRANDING.source, 'gi');

export function publicGameText(text: string): string {
  return text
    .replace(/\b(?:The\s+)?Legend of Zelda\s*:\s*Ocarina of Time\b/gi, 'the supported game')
    .replace(/\b(?:The\s+)?Legend of Zelda\b|\bOcarina of Time\b|\bZelda\b|\bOoT\b/gi, 'the game')
    .replace(/\bNintendo Switch(?: 2)?\b|\bSwitch 2\b/gi, 'the supported console')
    .replace(/\bSwitch Pro controllers?\b/gi, 'supported motion controllers')
    .replace(/\bSwitch mode\b/gi, 'compatible controller mode')
    .replace(/\bthe Switch\b/g, 'the console')
    .replace(/\bSwitch(?=,)/g, 'Original console')
    .replace(/\bNintendo \(Def\)/g, 'Default (A on right)')
    .replace(/\bNintendo\b/gi, 'original-console')
    .replace(/\bJoy-Cons?\b/gi, 'detachable controllers')
    .replace(/\bKokiri Forest\b/gi, 'the starting forest')
    .replace(/\bKokiri\b/gi, 'starting-area')
    .replace(/\b(?:the )?(?:Great )?Deku Tree\b/gi, 'the first dungeon')
    .replace(/\bDeku Sticks?\b/gi, 'wooden stick')
    .replace(/\bHyrule Field\b/gi, 'the main outdoor area')
    .replace(/\bHyrule Castle\b/gi, 'the castle')
    .replace(/\bHyrule\b/gi, 'the game world') // Some archived runs use only the world name.
    .replace(/\bKakariko(?: Village)?\b/gi, 'the village')
    .replace(/\bGoron City\b/gi, 'the mountain settlement')
    .replace(/\bZora(?:['’]?s)? (?:Rivers?|Domain|Fountain)\b/gi, 'the water region')
    .replace(/\bZoras?\b/gi, 'water-folk')
    .replace(/\bGorons?\b/gi, 'mountain-folk')
    .replace(/\bGanon(?:dorf)?['’]s Castle\b/gi, 'the final castle')
    .replace(/\bGanon(?:dorf)?\b/gi, 'the villain')
    .replace(/\bNavi waking Link\b/g, 'the opening wake-up scene')
    .replace(/\bNavi\b/g, 'the companion')
    .replace(/\b(?:adult|young) Link\b/gi, 'the player character')
    .replace(/\bLink['’]s\b/g, 'the player character’s')
    .replace(/\bEpona\b/g, 'the horse')
    .replace(/\bTriforce\b/gi, 'the quest relic')
    .replace(/\bocarina\b/gi, 'instrument')
    .replace(/\bDeku\b/gi, 'forest')
    // Players' issue titles name places and characters the list above doesn't know: whatever is left goes, so
    // a new title can't hold back every deployment.
    .replace(ANY_GAME_BRANDING, 'in-game');
}

/** Neutralize displayed prose before it reaches HTML, JSON and search. Keep URLs, versions and IDs exact. */
export function publicProgressItem<T extends {
  title: string; originalTitle: string; summary: string; workaround: string; labels: string[];
}>(item: T): T {
  return { ...item, title: publicGameText(item.title), originalTitle: publicGameText(item.originalTitle),
    summary: publicGameText(item.summary), workaround: publicGameText(item.workaround),
    labels: item.labels.map(publicGameText) };
}
