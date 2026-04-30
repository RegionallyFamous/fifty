# Fifty

**WooCommerce themes built by an AI agent on very strict rails. The rails are the point; the themes are the proof.**

WooCommerce powers more stores than Shopify and ships nothing like Shopify's themes. Rich and I think AI agents, with the right rails around them, can close that gap. So we're building the proof — a growing set of full WooCommerce storefronts, sharing one codebase, every demo booting in your browser, every rail in this repo.

The methodology is open source: dozens of lint checks that catch the WordPress-specific bugs LLMs love to ship, an editor-parity block validator that round-trips every block through the real `@wordpress/blocks` parser, a visual-regression suite that boots WordPress in headless Chromium and pixel-diffs every page, and a fussy Victorian shopkeeper named Woo-drow who gives the agent a voice and the rules a face. None of the themes ship a JavaScript bundle, a build step, a custom block, or a theme stylesheet beyond the WordPress header file — every theme directory is `theme.json` (the design system), block markup, and a small `functions.php` for WordPress/WooCommerce integration. You can read the whole thing in an afternoon, rebrand any of them in an evening, and ship to a real store on Monday. Every demo booting in your browser. Every rail in this repo.

WooCommerce knows we're doing this. You can read along.

## See them running

Every shipped theme — and every concept still in the queue — lives at **[demo.regionallyfamous.com](https://demo.regionallyfamous.com/)**. Each tile boots a fully-seeded WordPress + WooCommerce site **in your browser** — no install, no signup, no card. Give it 60 to 90 seconds on the first boot while it pulls the sample products and images.

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

The operator walkthroughs live in [`docs/shipping-a-theme.md`](docs/shipping-a-theme.md) for one theme and [`docs/batch-playbook.md`](docs/batch-playbook.md) for unattended batches. The plain-English factory overview is [`docs/how-it-works.md`](docs/how-it-works.md).

## What you get when you clone Obel

- **~25 templates** that cover every WordPress and WooCommerce page: homepage, archives, single product (with gallery + variations + reviews + upsells), cart, checkout, my-account dashboard, order confirmation, search, comments, 404, even coming-soon mode and the customer order detail view.
- **~10 starter patterns** (hero, featured products, value props, CTA banner, FAQ accordion, testimonials, footer columns) you can drag into the editor and edit in place.
- **A complete WooCommerce skin.** Cart, checkout, totals, mini-cart drawer, sale flashes, review stars, filters, breadcrumbs, the order-confirmation receipt — all themed, none of it screaming "stock WooCommerce".
- **A `playground/blueprint.json`** so anyone can boot your theme in a browser with one link, with sample products, sample orders, and a logged-in customer — exactly like the demos at the top of this README.
- **Zero JavaScript bundles. Zero custom blocks. Zero `node_modules`. Zero dependencies.**

## The rails, in plain English

These are the rails the agent operates inside. None of them are hidden — they're all in this repo, they all earn their keep, and they're how a swarm of LLM sessions across this codebase produces work that stays consistent enough to ship.

- **No CSS files. No JavaScript bundle. No build step.** Look at any theme directory: `theme.json` (the design system), `templates/` (block markup), `parts/` (header, footer, mini-cart), `patterns/` (drag-into-editor sections), `functions.php` (WordPress/WooCommerce filters plus the few documented inline scripts for swatches, payment icons, and view transitions). That's it. No `package.json`, no `webpack.config.js`, no `style.scss`, no `dist/`. The look comes from design tokens that the block editor reads natively. You edit a value, the editor updates instantly.

- **Wildly different stores from the same code.** Look at the demos again — Chonk and Lysholm couldn't look more different from each other, and they're literally clones of the same templates. Only the design tokens differ. That's the whole pitch in one sentence.

- **A real visual test in the gate.** A Python script (`bin/snap.py`) boots WordPress + WooCommerce locally for each changed theme, opens it in a real Chromium browser via Playwright, and screenshots the storefront matrix across phone, tablet, desktop, and wide viewports. Then it diffs the screenshots against committed reference images and tells you what changed. Fast proof runs can deliberately scope to mobile + desktop; PR and release gates use the broader matrix. So you don't push a homepage that has the cart sidebar at 60 pixels wide because you renamed a CSS class three commits ago.

- **Bug-catchers built specifically for WordPress's footguns.** Beyond the usual accessibility checks (axe-core runs on every snap), there are dozens of hand-written checks for the bugs WP and WC themes actually break on: oversized images, missing `alt` attributes, sidebars rendering 60px wide on desktop, "duplicate view-transition-name" warnings that silently abort native page transitions, leaked PHP debug output, raw `__()` translation tokens that didn't get translated, ellipsis truncation actively hiding content, brand-affecting filters smuggled into the demo-only `playground/` directory where they evaporate the moment a Proprietor downloads the theme, two themes shipping the exact same WooCommerce microcopy override (so every shop in the family reads "Proceed to Checkout" the same vanilla way). Each one names the file, points at the offending element, and tells you how to fix it.

- **One-click demos for everyone, including you.** Those `demo.regionallyfamous.com/<theme>/` links boot a real WordPress instance entirely in your browser via [WordPress Playground](https://wordpress.org/playground/). When you build your own theme on top of Fifty, you get the same thing free — your `playground/blueprint.json` is already wired up, just push to GitHub and share the link.

- **Native cross-page transitions.** Click around any of the demos and watch what happens between pages: the site title morphs from header into the product hero, post titles glide from archive cards into the single-post layout, header and footer persist across navigation. That's the browser's native [View Transitions API](https://developer.chrome.com/docs/web-platform/view-transitions/cross-document) doing the work through a shared `theme.json` CSS contract and a small inline classifier in `functions.php`. No JavaScript framework, no SPA shell, no router.

- **Accessibility is part of the gate.** A hand-written contrast checker runs on every theme's color palette and fails the build if text or UI states fall below the configured contrast floors. There's a separate hover/focus check for the "the accent color collapsed to invisible against the base" footgun. axe-core runs inside the snap framework, and new serious findings block the build instead of becoming TODOs.

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

The checked-in docs under [`docs/`](docs/) are the source of truth and are mirrored to the [wiki](https://github.com/RegionallyFamous/fifty/wiki). The five-stage factory — Ideate → Design → Verify → Self-heal → Ship — is walked through end-to-end in [How it works](docs/how-it-works.md) (plain-language overview + mermaid diagram).

| If you want to... | Read |
|---|---|
| Understand the pipeline end-to-end | [How it works](docs/how-it-works.md) |
| Ship one new theme | [Shipping a theme](docs/shipping-a-theme.md) |
| Ship a batch of themes in one pass | [Batch playbook](docs/batch-playbook.md) |
| Try a theme in WordPress Playground | [demo.regionallyfamous.com](https://demo.regionallyfamous.com/) |
| Browse concepts on the bench | [Concept queue](https://demo.regionallyfamous.com/concepts/) |
| Install a theme into a real WordPress instance | Copy the chosen `<theme>/` directory into `wp-content/themes/` and activate it |
| Make your own theme variant from scratch | [Shipping a theme](docs/shipping-a-theme.md) |
| See the layout and what every directory does | [`AGENTS.md`](AGENTS.md) |
| Run the build, validators, and the snapshot framework | [`AGENTS.md` tooling sections](AGENTS.md) · [`tests/visual-baseline/README.md`](tests/visual-baseline/README.md) |
| Edit existing themes safely | [`AGENTS.md`](AGENTS.md) plus the theme's own `AGENTS.md` and `INDEX.md` |
| Deep dive into one theme | That theme's `README.md`, `INDEX.md`, `AGENTS.md`, and `design-intent.md` |
| Use Fifty with Cursor / Claude / ChatGPT | [`AGENTS.md`](AGENTS.md) and [`AGENT-PERSONA.md`](AGENT-PERSONA.md) |
| Meet the agent persona | [`AGENT-PERSONA.md`](./AGENT-PERSONA.md) |

If you're an agent working in this repo, [`AGENTS.md`](./AGENTS.md) at the root is the load-bearing file. Read it first, then the per-theme `AGENTS.md`, then `INDEX.md` for whichever theme you're touching.

## License

GPL-2.0-or-later. Use it commercially, fork it, sell it, rebrand it. See [`LICENSE`](./LICENSE).
