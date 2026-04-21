# Fifty

**Five full WooCommerce stores. One shared codebase. Make one your own in an afternoon.**

Most WordPress theme projects are a graveyard of CSS files, build configs, and dependencies that haven't aged well. Fifty is the opposite: every theme in this repo is just block markup, a list of design values, and a tiny PHP file. You change about ten of those values and the whole storefront re-skins — buttons, links, focus rings, swatches, hover states, form inputs, "Add to cart" CTAs, transactional emails, the lot. You can read the whole thing in an afternoon. You can rebrand it in an evening. You can ship it to a real store on Monday.

## See them running

Each link below boots a fully-seeded WordPress + WooCommerce site **in your browser** — no install, no signup, no card. Give it 60 to 90 seconds on the first boot while it pulls the sample products and images.

| Theme | Vibe | Click here |
| --- | --- | --- |
| **Obel** | Editorial, soft, restrained | [demo.regionallyfamous.com/obel/](https://demo.regionallyfamous.com/obel/) |
| **Chonk** | Neo-brutalist, chunky, high-contrast | [demo.regionallyfamous.com/chonk/](https://demo.regionallyfamous.com/chonk/) |
| **Selvedge** | Workwear indigo, woven textures, raw edges | [demo.regionallyfamous.com/selvedge/](https://demo.regionallyfamous.com/selvedge/) |
| **Lysholm** | Quiet Nordic, white-on-white, blonde wood | [demo.regionallyfamous.com/lysholm/](https://demo.regionallyfamous.com/lysholm/) |
| **Aero** | Iridescent dark mode, glass surfaces, signal accents | [demo.regionallyfamous.com/aero/](https://demo.regionallyfamous.com/aero/) |

You land on the homepage as `admin / password`. From there click into the shop, a product, the (already pre-filled) cart, checkout, the customer dashboard, the journal, the 404. Sign in as `customer / customer` to see the customer side. Break stuff — it's disposable.

## Want to make your own?

Pick whichever theme is closest to the vibe you want and copy it:

```bash
python3 bin/clone.py mybrand
```

That gives you `mybrand/`, a sibling of Obel inside this repo. Open `mybrand/theme.json` — that one file is the entire design system — and start changing values:

- **The colors.** Six entries in `palette` define every color the theme uses. Want a coral-and-cream store? Change two of them. Every button, link, focus ring, hover state, form input, and "Add to cart" CTA picks it up.
- **The fonts.** `typography.fontFamilies` is a short list. Drop in a Google Font URL or a local file.
- **The shape.** `spacing.spacingScale`, `borderRadius`, `layout.contentSize` set the rhythm of the whole site. Tighter, looser, sharper, softer — three numbers each.

Hit reload in the WordPress site editor and the entire storefront re-skins live. No build step. No CSS to recompile. No browser cache to chase. The block editor reads `theme.json` directly.

When you've got something you like, ship it the same way you ship any other WordPress theme: drop the `mybrand/` directory into `wp-content/themes/` on a real site and activate it. Fifty themes are completely standard WordPress + WooCommerce — every block, every template, every WC hook is the official one. You're not locked into a framework or a page builder. You're not paying anyone a license fee. The entire project is GPL-2.0+, fork it and sell it.

The full nine-step walkthrough lives in [Adding a Theme](https://github.com/RegionallyFamous/fifty/wiki/Adding-a-Theme).

## What you get when you clone Obel

- **~25 templates** that cover every WordPress and WooCommerce page: homepage, archives, single product (with gallery + variations + reviews + upsells), cart, checkout, my-account dashboard, order confirmation, search, comments, 404, even coming-soon mode and the customer order detail view.
- **~10 starter patterns** (hero, featured products, value props, CTA banner, FAQ accordion, testimonials, footer columns) you can drag into the editor and edit in place.
- **A complete WooCommerce skin.** Cart, checkout, totals, mini-cart drawer, sale flashes, review stars, filters, breadcrumbs, the order-confirmation receipt — all themed, none of it screaming "stock WooCommerce".
- **A `playground/blueprint.json`** so anyone can boot your theme in a browser with one link, with sample products, sample orders, and a logged-in customer — exactly like the demos at the top of this README.
- **Zero JavaScript bundles. Zero custom blocks. Zero `node_modules`. Zero dependencies.**

## The cool engineering bits, in plain English

These are the parts that make the whole "ten values and you're done" thing actually work. None of them are hidden — they're all in this repo and they all earn their keep.

- **No CSS files. No JavaScript. No build step.** Look at any theme directory: `theme.json` (the design system), `templates/` (block markup), `parts/` (header, footer, mini-cart), `patterns/` (drag-into-editor sections), `functions.php` (a few WP filters). That's it. No `package.json`, no `webpack.config.js`, no `style.scss`, no `dist/`. The look comes entirely from design tokens that the block editor reads natively. You edit a value, the editor updates instantly.

- **Five very different stores from the same code.** Look at the demos again — Chonk and Lysholm couldn't look more different from each other, and they are literally clones of the same templates. Only the design tokens differ. That's the whole pitch in one sentence.

- **A real visual test on every commit.** A Python script (`bin/snap.py`) boots WordPress + WooCommerce locally for each theme, opens it in a real Chromium browser via Playwright, and screenshots every page at four screen sizes. Then it diffs the screenshots against committed reference images and tells you what changed. If something looks broken, the build fails. So you don't push a homepage that has the cart sidebar at 60 pixels wide because you renamed a CSS class three commits ago.

- **Bug-catchers built specifically for WordPress's footguns.** Beyond the usual accessibility checks (axe-core runs on every snap), there are about 35 hand-written checks for the bugs WP and WC themes actually break on: oversized images, missing `alt` attributes, sidebars rendering 60px wide on desktop, "duplicate view-transition-name" warnings that silently abort native page transitions, leaked PHP debug output, raw `__()` translation tokens that didn't get translated, ellipsis truncation actively hiding content, mu-plugins echoing duplicate HTML on shared WC loop hooks. Each one names the file, points at the offending element, and tells you how to fix it.

- **One-click demos for everyone, including you.** Those `demo.regionallyfamous.com/<theme>/` links boot a real WordPress instance entirely in your browser via [WordPress Playground](https://wordpress.org/playground/). When you build your own theme on top of Fifty, you get the same thing free — your `playground/blueprint.json` is already wired up, just push to GitHub and share the link.

- **Native cross-page transitions.** Click around any of the demos and watch what happens between pages: the site title morphs from header into the product hero, post titles glide from archive cards into the single-post layout, header and footer persist across navigation. That's the browser's native [View Transitions API](https://developer.chrome.com/docs/web-platform/view-transitions/cross-document) doing the work — about 20 lines of CSS in `theme.json`. No JavaScript framework, no SPA shell, no router.

- **Accessibility passes, every time.** A hand-written contrast checker runs on every theme's color palette and fails the build if any text drops below the WCAG AA 4.5:1 threshold or any UI element drops below 3:1. There's a separate hover/focus check for the "the accent color collapsed to invisible against the base" footgun. axe-core runs on every page in the snap framework. No theme in this repo ships with a known accessibility violation.

- **Built for AI agents, with a personality to match.** Every theme has an `AGENTS.md`, an `INDEX.md`, a `CHANGELOG.md`, and a `SYSTEM-PROMPT.md`. The repo-root [`AGENTS.md`](./AGENTS.md) is a 2000-line catalog of every footgun the project has hit, with the regression history and the rule that catches it. Drop the repo into Cursor or Claude and they can ship a brand-new theme variant in one session, because every gotcha has a comment and every rule has a check. They'll also greet you in character — see the next section.

## Working with the agent

The LLM working in this repo doesn't speak as a generic assistant. It speaks as **Woo-drow**, a fussy Victorian shopdresser who keeps a small workshop on Theodora Row and has dressed many a shop in his time. He addresses you as "the Proprietor," refers to the homepage as the shop window, the product grid as the shelves, the checkout as the till, `theme.json` as the design card, and to default WooCommerce strings bleeding through as "the factory labels showing." He has firm opinions about craft and will push back, politely, when you ask him to do something he thinks is a mistake. He yields if you insist.

Why bother? Three reasons:

1. **The voice carries the rules.** When the agent says "the factory labels are showing," it's also reminding itself (and you) that there's a hard rule about default WC strings, and a check that enforces it. Pet peeves and gate failures map onto each other one-for-one. The persona is the rulebook with a face.
2. **It makes the working relationship feel like one.** A clarifying question delivered as "A small matter, if I may. Is the hero image meant to be the headline of the establishment, or merely a pleasant flourish?" reads like a tradesman talking to a client, not a chatbot waiting for a token quota. Sessions feel like sessions.
3. **You can turn it off in one phrase.** Say "drop the act," "plain English," or "stop the shopkeeper thing" and the voice goes away for the rest of the session, without comment or sulking. Resume just as easily.

The voice lives in chat only. Anything written to disk — this README, theme templates, commit messages, code comments, changelog entries — reverts to plain prose. The committed codebase reads like the rest of the codebase. So if you're scanning the repo wondering whether Woo-drow is going to leak into your `style.css`, he isn't.

The full persona spec is in [`AGENT-PERSONA.md`](./AGENT-PERSONA.md). The short inline version that ships with every theme's system prompt is in each `<theme>/SYSTEM-PROMPT.md`. If you'd rather work with a vanilla assistant, delete the persona block from the system prompt and the rest of the file still works on its own.

## Documentation

The full technical reference lives in the [wiki](https://github.com/RegionallyFamous/fifty/wiki):

| If you want to... | Read |
|---|---|
| Try a theme in WordPress Playground (full URL tables, blueprint internals) | [Getting Started](https://github.com/RegionallyFamous/fifty/wiki/Getting-Started) |
| Install a theme into a real WordPress instance | [Getting Started → Local install](https://github.com/RegionallyFamous/fifty/wiki/Getting-Started#loading-themes-into-wordpress) |
| Make your own theme variant from scratch | [Adding a Theme](https://github.com/RegionallyFamous/fifty/wiki/Adding-a-Theme) |
| See the layout and what every directory does | [Project Structure](https://github.com/RegionallyFamous/fifty/wiki/Project-Structure) |
| Run the build, validators, and the snapshot framework | [Tooling](https://github.com/RegionallyFamous/fifty/wiki/Tooling) · [Visual Snapshots](https://github.com/RegionallyFamous/fifty/wiki/Visual-Snapshots) |
| Edit existing themes safely | [Working in the Repo](https://github.com/RegionallyFamous/fifty/wiki/Working-in-the-Repo) |
| Deep dive into one theme | [Architecture](https://github.com/RegionallyFamous/fifty/wiki/Architecture) · [Design Tokens](https://github.com/RegionallyFamous/fifty/wiki/Design-Tokens) · [Block Reference](https://github.com/RegionallyFamous/fifty/wiki/Block-Reference) · [Templates](https://github.com/RegionallyFamous/fifty/wiki/Templates) |
| Use Fifty with Cursor / Claude / ChatGPT | [Working with LLMs](https://github.com/RegionallyFamous/fifty/wiki/Working-with-LLMs) |
| Meet the agent persona | [`AGENT-PERSONA.md`](./AGENT-PERSONA.md) |

If you're an agent working in this repo, [`AGENTS.md`](./AGENTS.md) at the root is the load-bearing file. Read it first, then the per-theme `AGENTS.md`, then `INDEX.md` for whichever theme you're touching.

## License

GPL-2.0-or-later. Use it commercially, fork it, sell it, rebrand it. See [`LICENSE`](./LICENSE).
