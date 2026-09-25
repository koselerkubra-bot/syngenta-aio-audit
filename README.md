# Technical AIO Status Dashboard

A small, self-contained tool that scans a Syngenta website, checks every
page against the on-page checklist used by the `syngenta-seo-aeo-optimizer`
skill (meta title and description, H1, H2 phrasing, FAQ schema, image alt
text, freshness signal, and whether the page's core content actually
reaches AI crawlers), and publishes the current state as a static
dashboard. It supports **multiple sites**, each with its own dashboard,
listed on one shared hub page.

It runs on a weekly schedule via GitHub Actions and needs no AI model,
no API key, and no connection back to Claude at run time. Every check
is deterministic Python reading real, freshly fetched HTML.

**This tool reports what is true about each site right now. It does not
generate recommendations or an action plan.** That judgment is left to
whoever reads the dashboard.

---

## 1. Getting this running on GitHub

1. **Create a repository** on your GitHub account (public or private,
   either works) and push this folder to it:
   ```bash
   cd aio-audit-tool
   git init
   git add .
   git commit -m "Initial commit: technical AIO audit tool"
   git branch -M main
   git remote add origin https://github.com/<your-username>/<repo-name>.git
   git push -u origin main
   ```
2. **Turn on GitHub Pages.** In the repository, go to
   **Settings > Pages**. Under "Build and deployment", set
   **Source: Deploy from a branch**, **Branch: main**, **Folder: /docs**.
   Save. The dashboard will be reachable at
   `https://<your-username>.github.io/<repo-name>/` within a minute or two.
3. **Allow the workflow to commit results back.** Go to
   **Settings > Actions > General**, scroll to "Workflow permissions",
   select **Read and write permissions**, and save. Without this, the
   weekly job can run the scan but can't save the updated dashboard.
4. **Run it once by hand** to confirm everything works, rather than
   waiting for Monday. Go to the **Actions** tab, click
   **Weekly AIO Scan** in the left sidebar, click **Run workflow**
   (top right), leave the fields empty, and click the green
   **Run workflow** button. Watch the run under **Actions**; it takes a
   while (every page is fetched twice: raw and rendered). When it
   finishes, refresh your GitHub Pages URL.

After that, it runs on its own every Monday at 06:00 UTC. No further steps.

---

## 2. Adding another site's URL to analyze

This is also done from the **Actions** tab, no code or file editing needed:

1. Go to **Actions > Weekly AIO Scan > Run workflow**.
2. In the **add_url** field, paste any URL on the site you want to add
   (the homepage is easiest, but any page on that domain works, its
   domain root and `/sitemap.xml` are worked out automatically). For
   example: `https://www.syngenta.com.mx/`
3. Optionally fill in **site_name** with a display name (e.g.
   "Syngenta Mexico"). If left empty, the domain itself is used.
4. Click the green **Run workflow** button.

That single run does two things: it adds the site to
`config/sites.yaml` (so every future weekly run includes it
automatically, alongside every other tracked site), and scans it
immediately, so its dashboard appears without waiting for next Monday.

The hub page at your GitHub Pages URL will now list every tracked site,
each with a link to its own dashboard.

**To remove a site later:** delete its entry from `config/sites.yaml`
directly in the repository (and, if you want to clean up, its
`data/<slug>/` and `docs/<slug>/` folders), commit, and it drops out of
future runs and out of the hub page.

---

## What it checks, per page

| Check | How |
|---|---|
| JS content gap | Fetches the page twice: once as raw HTML (what most AI crawlers see), once through a headless browser (what a person or Googlebot sees). Flags a large gap between the two. |
| Meta title / description | Length, and whether either is missing. |
| H1 | Present, and exactly one. |
| H2 phrasing | Rough heuristic: does each heading read like a question. |
| Schema (JSON-LD) | Every `@type` found on the page, including inside `@graph`; flags whether `FAQPage` is present. |
| Image alt text | Empty alt text, filename-shaped alt text, and missing/broken `src`. |
| Freshness signal | Looks for a visible "last updated" style phrase. |
| robots.txt | Whether GPTBot, Anthropic-AI, ClaudeBot, PerplexityBot, Google-Extended, and CCBot are blocked, site-wide (not per page). |

Page discovery is fully automatic per site: the tool reads that site's
`sitemap.xml` (following nested sitemap indexes), with the `Sitemap:`
lines in `robots.txt` as a supplementary source.

## Project layout

```
aio-audit-tool/
├── scanner.py                    # entry point, run this
├── config.yaml                   # shared thresholds, applies to every site
├── config/sites.yaml             # the list of tracked sites (name, domain, sitemap)
├── requirements.txt
├── src/
│   ├── sites_config.py           # load/save config/sites.yaml, --add-url logic
│   ├── sitemap_discovery.py      # finds every page URL for one site
│   ├── fetcher.py                # raw fetch + headless-browser fetch
│   ├── analyzer.py               # per-page checklist logic
│   ├── aggregator.py             # site-wide summary stats
│   ├── robots_check.py           # AI-bot robots.txt check
│   ├── storage.py                # JSON read/write, weekly history
│   └── dashboard.py              # renders each site's dashboard + the hub page
├── templates/
│   ├── dashboard.html.j2         # one site's dashboard
│   └── hub.html.j2               # the "all tracked sites" landing page
├── data/<slug>/                  # one folder per site: latest run + weekly history
├── docs/
│   ├── index.html                # the hub page (GitHub Pages root)
│   └── <slug>/index.html         # one dashboard per site
└── .github/workflows/weekly-scan.yml
```

## Running it locally

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

Quick test on a handful of pages before scanning a whole site:

```bash
python scanner.py --site syngenta-ca --limit 10
```

Scan every tracked site (this is what the weekly job runs):

```bash
python scanner.py --all
```

Add and scan a new site:

```bash
python scanner.py --add-url https://www.syngenta.com.mx/ --name "Syngenta Mexico"
```

Then open `docs/index.html` (the hub) or `docs/<slug>/index.html`
(one site's dashboard) in a browser.

A full run takes a while: every page on every site is fetched twice
(raw and rendered), with a politeness delay between pages. That's
exactly why this is meant to run unattended, on a schedule, rather
than interactively.

## Known limitations

- **H2-as-a-question** and **freshness signal** are simple text
  heuristics, not a guarantee. Treat them as directional, not exact.
- The **JS content gap** thresholds in `config.yaml`
  (`js_gap_word_threshold_ratio`, `js_gap_min_word_diff`) are a
  reasonable starting point, not a universal constant. If a dashboard
  flags pages that are simply short and image-heavy by design, loosen
  the threshold.
- **Schema detection** confirms a schema block is present and what type
  it declares; it does not validate the block's field-level correctness
  (for that, use Google's Rich Results Test).
- This tool does not distinguish an intentionally thin page (a simple
  redirect or listing page) from a page that should have rich content
  but doesn't. Use the page-type grouping and your own judgment.

## Where this comes from

The checklist here mirrors `references/aeo-principles.md` from the
`syngenta-seo-aeo-optimizer` skill: the same nine on-page elements, the
same schema-by-page-type expectations, and the same JS-rendering
concern first surfaced during a manual audit of the Axial and
Boundary&reg; LQD product pages on syngenta.ca.
