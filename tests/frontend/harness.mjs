/*
 * Shared loader for the bundled card under jsdom.
 *
 * HA serves the card with `add_extra_js_url`, i.e. as <script type="module">, and the card
 * uses `import.meta.url` to resolve its sibling map renderer. jsdom cannot evaluate module
 * scripts at all, so both suites inject the card as a CLASSIC script — where the bare token
 * `import.meta` is a PARSE-TIME SyntaxError that would take the whole file down.
 *
 * Substituting a literal module URL is what lets the real, unmodified source run here. It is
 * also the only way to assert the thing that substitution would otherwise hide: that the card
 * carries its own `?v=<version>` cache-bust across to the renderer import, so a version bump
 * busts both files together instead of pairing a fresh card with a stale cached renderer.
 */
import fs from "node:fs";

export const CARD_PATH = new URL(
  "../../custom_components/robovac_mqtt/frontend/eufy-clean-card.js",
  import.meta.url
);

/** The module URL the card believes it was served from (matches the real `?v=` shape). */
export const CARD_MODULE_URL = "https://localhost/robovac_mqtt/eufy-clean-card.js?v=1.2.3";

export function cardSource(moduleUrl = CARD_MODULE_URL) {
  return fs
    .readFileSync(CARD_PATH, "utf8")
    .replace(/\bimport\.meta\.url\b/g, JSON.stringify(moduleUrl));
}
