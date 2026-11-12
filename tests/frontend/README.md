# eufy-clean-card jsdom harness

Runs `custom_components/robovac_mqtt/frontend/eufy-clean-card.js` inside jsdom
against a hand-built fake `hass`, and asserts on the resulting shadow DOM. It is
the only automated coverage the card has — the Python suite never loads it.

```sh
cd tests/frontend
npm install       # once; node_modules is gitignored
npm test
```

Exit code is non-zero on the first failing assertion count, so it drops straight
into CI. It needs no browser and no Home Assistant.
