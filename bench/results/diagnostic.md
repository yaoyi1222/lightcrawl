# Diagnostic report

Pipelines:
- P0: raw HTML (baseline)
- P1: readability + markdownify (current)
- P2: deep-clean HTML (safe tag set), return HTML
- P2b: deep-clean HTML aggressive (plan.md tag set + strip class/id), HTML
- P3: deep-clean DOM (safe), markdownify body
- P3b: deep-clean DOM (aggressive), markdownify body
- P4: trafilatura

## Per-URL results

| URL (cat) | DOM h_total | Pipeline | Tokens | MD headings | Residue |
|---|---:|---|---:|---:|:--:|
| https://en.wikipedia.org/wiki/Claude_Shannon (wiki) | 31 | P0_raw | 171233 | 0 | yes |
|  |  | P1_readability_md | 31746 | 9 |  |
|  |  | P2_clean_html_safe | 150330 | 0 |  |
|  |  | P2b_clean_html_aggressive | 113374 | 0 |  |
|  |  | P3_clean_md | 61959 | 31 |  |
|  |  | P3b_clean_md_aggressive | 56365 | 29 |  |
|  |  | P4_trafilatura | 27950 | 25 |  |
| https://en.wikipedia.org/wiki/Transformer_(deep_learning_architecture) (wiki) | 49 | P0_raw | 233448 | 0 | yes |
|  |  | P1_readability_md | 50399 | 19 |  |
|  |  | P2_clean_html_safe | 136999 | 0 |  |
|  |  | P2b_clean_html_aggressive | 100679 | 0 |  |
|  |  | P3_clean_md | 52114 | 49 |  |
|  |  | P3b_clean_md_aggressive | 47057 | 47 |  |
|  |  | P4_trafilatura | 28488 | 36 |  |
| https://docs.python.org/3/library/asyncio.html (static_doc) | 9 | P0_raw | 6692 | 0 | yes |
|  |  | P1_readability_md | 416 | 1 |  |
|  |  | P2_clean_html_safe | 4396 | 0 |  |
|  |  | P2b_clean_html_aggressive | 2767 | 0 |  |
|  |  | P3_clean_md | 1586 | 9 |  |
|  |  | P3b_clean_md_aggressive | 1457 | 6 |  |
|  |  | P4_trafilatura | 720 | 0 |  |
| https://docs.python.org/3/library/typing.html (static_doc) | 42 | P0_raw | 154826 | 0 | yes |
|  |  | P1_readability_md | 33963 | 26 |  |
|  |  | P2_clean_html_safe | 151203 | 0 |  |
|  |  | P2b_clean_html_aggressive | 98549 | 0 |  |
|  |  | P3_clean_md | 43616 | 42 |  |
|  |  | P3b_clean_md_aggressive | 43002 | 38 |  |
|  |  | P4_trafilatura | 32709 | 34 |  |
| https://raw.githubusercontent.com/python/cpython/main/README.rst (github) | 0 | P0_raw | 2031 | 0 |  |
|  |  | P1_readability_md | 1808 | 0 |  |
|  |  | P2_clean_html_safe | 2013 | 0 |  |
|  |  | P2b_clean_html_aggressive | 2013 | 0 |  |
|  |  | P3_clean_md | 1808 | 0 |  |
|  |  | P3b_clean_md_aggressive | 1808 | 0 |  |
|  |  | P4_trafilatura | 0 | 0 |  |
| https://github.com/anthropics/anthropic-sdk-python (github) | 35 | P0_raw | 127018 | 0 |  |
|  |  | P1_readability_md | 333 | 0 |  |
|  |  | P2_clean_html_safe | 31050 | 0 |  |
|  |  | P2b_clean_html_aggressive | 9750 | 0 |  |
|  |  | P3_clean_md | 4010 | 33 |  |
|  |  | P3b_clean_md_aggressive | 2332 | 25 |  |
|  |  | P4_trafilatura | 207 | 0 |  |
| https://news.ycombinator.com/ (news) | — | FETCH FAILED | — | — | — |
| https://lite.cnn.com/ (news) | 0 | P0_raw | 92505 | 0 | yes |
|  |  | P1_readability_md | 0 | 0 |  |
|  |  | P2_clean_html_safe | 5830 | 0 |  |
|  |  | P2b_clean_html_aggressive | 5098 | 0 |  |
|  |  | P3_clean_md | 4128 | 0 |  |
|  |  | P3b_clean_md_aggressive | 4036 | 0 |  |
|  |  | P4_trafilatura | 4028 | 0 |  |
| https://react.dev/learn (spa) | 16 | P0_raw | 91905 | 0 | yes |
|  |  | P1_readability_md | 3317 | 12 | yes |
|  |  | P2_clean_html_safe | 30545 | 0 |  |
|  |  | P2b_clean_html_aggressive | 11826 | 0 |  |
|  |  | P3_clean_md | 4066 | 15 | yes |
|  |  | P3b_clean_md_aggressive | 3484 | 13 | yes |
|  |  | P4_trafilatura | 3110 | 12 | yes |
| https://www.alltrails.com/ (cloudflare) | 18 | P0_raw | 113241 | 0 | yes |
|  |  | P1_readability_md | 29 | 0 |  |
|  |  | P2_clean_html_safe | 12023 | 0 |  |
|  |  | P2b_clean_html_aggressive | 3574 | 0 |  |
|  |  | P3_clean_md | 2167 | 10 |  |
|  |  | P3b_clean_md_aggressive | 1603 | 7 |  |
|  |  | P4_trafilatura | 77 | 4 |  |

## Aggregate (sum across successful URLs)

| Pipeline | Σ tokens | Σ MD headings | URLs w/ residue |
|---|---:|---:|---:|
| P0_raw | 992899 | 0 | 7 |
| P1_readability_md | 122011 | 67 | 1 |
| P2_clean_html_safe | 524389 | 0 | 0 |
| P2b_clean_html_aggressive | 347630 | 0 | 0 |
| P3_clean_md | 175454 | 189 | 1 |
| P3b_clean_md_aggressive | 161144 | 165 | 1 |
| P4_trafilatura | 97289 | 111 | 1 |

## DOM heading distribution (ground truth)

| URL | h1 | h2 | h3 | h4 | h5 | h6 | total |
|---|---:|---:|---:|---:|---:|---:|---:|
| https://en.wikipedia.org/wiki/Claude_Shannon | 1 | 12 | 16 | 2 | 0 | 0 | 31 |
| https://en.wikipedia.org/wiki/Transformer_(deep_learning_architecture) | 1 | 11 | 25 | 12 | 0 | 0 | 49 |
| https://docs.python.org/3/library/asyncio.html | 1 | 0 | 4 | 4 | 0 | 0 | 9 |
| https://docs.python.org/3/library/typing.html | 1 | 13 | 13 | 15 | 0 | 0 | 42 |
| https://raw.githubusercontent.com/python/cpython/main/README.rst | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| https://github.com/anthropics/anthropic-sdk-python | 5 | 18 | 12 | 0 | 0 | 0 | 35 |
| https://lite.cnn.com/ | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| https://react.dev/learn | 1 | 12 | 3 | 0 | 0 | 0 | 16 |
| https://www.alltrails.com/ | 1 | 17 | 0 | 0 | 0 | 0 | 18 |

## Sample heads (first ~160 chars)

### https://en.wikipedia.org/wiki/Claude_Shannon

- **P0_raw** — `<!DOCTYPE html> <html class="client-nojs vector-feature-language-in-header-enabled vector-feature-language-in-main-menu-disabled vector-feature-language-in-main`
- **P1_readability_md** — `American mathematician (1916–2001)  | Claude Shannon | | | --- | --- | |  | | | Born | Claude Elwood Shannon  (1916-04-30)April 30, 1916 | | Died | February 24,`
- **P2_clean_html_safe** — `<body class="skin--responsive skin-vector skin-vector-search-vue mediawiki ltr sitedir-ltr mw-hide-empty-elt ns-0 ns-subject mw-editable page-Claude_Shannon roo`
- **P2b_clean_html_aggressive** — `<body> <div aria-live="polite"></div><a href="#bodyContent">Jump to content</a> <div>  </div> <div>  <div>  <div>  <div></div>  </div>  <div>  <div>  <div>  </d`
- **P3_clean_md** — `[Jump to content](#bodyContent)  Main menu  Navigation  * [Main page](/wiki/Main_Page "Visit the main page [z]") * [Contents](/wiki/Wikipedia:Contents "Guides t`
- **P3b_clean_md_aggressive** — `[Jump to content](#bodyContent)  From Wikipedia, the free encyclopedia  |  |  | | --- | --- | |  | This article **needs additional citations for [verification](`
- **P4_trafilatura** — `# Claude Shannon  This article needs additional citations for . (April 2026) |  Claude Shannon | | |---|---| | Born | Claude Elwood Shannon April 30, 1916 | | D`

### https://en.wikipedia.org/wiki/Transformer_(deep_learning_architecture)

- **P0_raw** — `<!DOCTYPE html> <html class="client-nojs vector-feature-language-in-header-enabled vector-feature-language-in-main-menu-disabled vector-feature-language-in-main`
- **P1_readability_md** — `Algorithm for modelling sequential data  [![](//upload.wikimedia.org/wikipedia/commons/thumb/3/34/Transformer%2C_full_architecture.png/250px-Transformer%2C_full`
- **P2_clean_html_safe** — `<body class="skin--responsive skin-vector skin-vector-search-vue mediawiki ltr sitedir-ltr mw-hide-empty-elt ns-0 ns-subject mw-editable page-Transformer_deep_l`
- **P2b_clean_html_aggressive** — `<body> <div aria-live="polite"></div><a href="#bodyContent">Jump to content</a> <div>  </div> <div>  <div>  <div>  <div></div>  </div>  <div>  <div>  <div>  </d`
- **P3_clean_md** — `[Jump to content](#bodyContent)  Main menu  Navigation  * [Main page](/wiki/Main_Page "Visit the main page [z]") * [Contents](/wiki/Wikipedia:Contents "Guides t`
- **P3b_clean_md_aggressive** — `[Jump to content](#bodyContent)  From Wikipedia, the free encyclopedia  (Redirected from [Transformer (deep learning architecture)](/w/index.php?title=Transform`
- **P4_trafilatura** — `# Transformer (deep learning)  [Transformer (deep learning architecture)](/w/index.php?title=Transformer_(deep_learning_architecture)&redirect=no))  | Part of a`

### https://docs.python.org/3/library/asyncio.html

- **P0_raw** — `<!DOCTYPE html>  <html lang="en" data-content_root="../">   <head>     <meta charset="utf-8" />     <meta name="viewport" content="width=device-width, initial-s`
- **P1_readability_md** — `# `asyncio` — Asynchronous I/O  ---  asyncio is a library to write **concurrent** code using the **async/await** syntax.  asyncio is used as a foundation for mu`
- **P2_clean_html_safe** — `<body> <div class="mobile-nav">  <nav class="nav-content" role="navigation">  <label for="menuToggler" class="toggler__label">  <span></span>  </label>  <span c`
- **P2b_clean_html_aggressive** — `<body> <div>  <div>  </div> </div>     <div role="navigation" aria-label="Related">  <h3>Navigation</h3>  <ul>  <li>  <a href="../genindex.html" title="General `
- **P3_clean_md** — `Theme  #### Previous topic  [Networking and Interprocess Communication](ipc.html "previous chapter")  #### Next topic  [Runners](asyncio-runner.html "next chapt`
- **P3b_clean_md_aggressive** — `### Navigation  * [index](../genindex.html "General Index") * [modules](../py-modindex.html "Python Module Index") | * [next](asyncio-runner.html "Runners") | *`
- **P4_trafilatura** — ``asyncio`  — Asynchronous I/O[¶](#module-asyncio)  asyncio is a library to write **concurrent** code using the **async/await** syntax.  asyncio is used as a fou`

### https://docs.python.org/3/library/typing.html

- **P0_raw** — `<!DOCTYPE html>  <html lang="en" data-content_root="../">   <head>     <meta charset="utf-8" />     <meta name="viewport" content="width=device-width, initial-s`
- **P1_readability_md** — `# `typing` — Support for type hints  **Source code:** [Lib/typing.py](https://github.com/python/cpython/tree/3.14/Lib/typing.py)  Note  The Python runtime does `
- **P2_clean_html_safe** — `<body> <div class="mobile-nav">  <nav class="nav-content" role="navigation">  <label for="menuToggler" class="toggler__label">  <span></span>  </label>  <span c`
- **P2b_clean_html_aggressive** — `<body> <div>  <div>  </div> </div>     <div role="navigation" aria-label="Related">  <h3>Navigation</h3>  <ul>  <li>  <a href="../genindex.html" title="General `
- **P3_clean_md** — `Theme  ### [Table of Contents](../contents.html)  * [`typing` — Support for type hints](#)   + [Specification for the Python Type System](#specification-for-the`
- **P3b_clean_md_aggressive** — `### Navigation  * [index](../genindex.html "General Index") * [modules](../py-modindex.html "Python Module Index") | * [next](pydoc.html "pydoc — Documentation `
- **P4_trafilatura** — ``typing`  — Support for type hints[¶](#typing-support-for-type-hints)  Added in version 3.5.  **Source code:** [Lib/typing.py](https://github.com/python/cpython`

### https://raw.githubusercontent.com/python/cpython/main/README.rst

- **P0_raw** — `This is Python version 3.15.0 alpha 8 =====================================  .. image:: https://github.com/python/cpython/actions/workflows/build.yml/badge.svg?`
- **P1_readability_md** — `This is Python version 3.15.0 alpha 8 ===================================== .. image:: https://github.com/python/cpython/actions/workflows/build.yml/badge.svg?b`
- **P2_clean_html_safe** — `<span>This is Python version 3.15.0 alpha 8 =====================================  .. image:: https://github.com/python/cpython/actions/workflows/build.yml/badg`
- **P2b_clean_html_aggressive** — `<span>This is Python version 3.15.0 alpha 8 =====================================  .. image:: https://github.com/python/cpython/actions/workflows/build.yml/badg`
- **P3_clean_md** — `This is Python version 3.15.0 alpha 8 ===================================== .. image:: https://github.com/python/cpython/actions/workflows/build.yml/badge.svg?b`
- **P3b_clean_md_aggressive** — `This is Python version 3.15.0 alpha 8 ===================================== .. image:: https://github.com/python/cpython/actions/workflows/build.yml/badge.svg?b`
- **P4_trafilatura** — ``

### https://github.com/anthropics/anthropic-sdk-python

- **P0_raw** — `      <!DOCTYPE html> <html   lang="en"      data-color-mode="auto" data-light-theme="light" data-dark-theme="dark"   data-a11y-animated-images="system" data-a1`
- **P1_readability_md** — `[![PyPI version](https://camo.githubusercontent.com/235acf1b166b8c9131d9ed3a734ac97201303a6b6c97096d2aad3424d98609b8/68747470733a2f2f696d672e736869656c64732e696`
- **P2_clean_html_safe** — `<body class="logged-out env-production page-responsive" style="word-wrap: break-word;">  <div data-turbo-body class="logged-out env-production page-responsive" `
- **P2b_clean_html_aggressive** — `<body>  <div data-turbo-body>  <div role="region" data-turbo-permanent></div>     <div>  <a href="#start-of-content" data-skip-target-assigned="false">Skip to c`
- **P3_clean_md** — `[Skip to content](#start-of-content)  ## Navigation Menu  [Sign in](/login?return_to=https%3A%2F%2Fgithub.com%2Fanthropics%2Fanthropic-sdk-python)  Appearance s`
- **P3b_clean_md_aggressive** — `[Skip to content](#start-of-content)  You signed in with another tab or window. Reload to refresh your session. You signed out in another tab or window. Reload `
- **P4_trafilatura** — `The Claude SDK for Python provides access to the [Claude API](https://docs.anthropic.com/en/api/) from Python applications.  Full documentation is available at `

### https://lite.cnn.com/

- **P0_raw** — `  <!DOCTYPE html> <html lang="en" data-layout-uri="cms.cnn.com/_layouts/layout-homepage/instances/cnnlite-v1@published">   <head><style>:root{--primitive-color-`
- **P1_readability_md** — ``
- **P2_clean_html_safe** — `<body class="cnn">  <header class="header--lite">  <a href="/" class="title">CNN</a>  <span>5/5/2026</span> </header>   <div class="layout-homepage__lite">  <di`
- **P2b_clean_html_aggressive** — `<body>  <div>  <div data-uri="cms.cnn.com/_components/static/instances/cnnlite-v1@published" data-unselectable="true">  <section data-tabcontent="Content" data-`
- **P3_clean_md** — `[CNN](/) 5/5/2026  Latest Stories  * [How traffic through the Strait of Hormuz shrank to a trickle – a visual deep dive](/2026/04/29/world/iran-war-gulf-hormuz-`
- **P3b_clean_md_aggressive** — `Latest Stories  * [How traffic through the Strait of Hormuz shrank to a trickle – a visual deep dive](/2026/04/29/world/iran-war-gulf-hormuz-shipping-maps-intl-`
- **P4_trafilatura** — `Latest Stories  - [How traffic through the Strait of Hormuz shrank to a trickle – a visual deep dive](/2026/04/29/world/iran-war-gulf-hormuz-shipping-maps-intl-`

### https://react.dev/learn

- **P0_raw** — `<!DOCTYPE html><html lang="en" dir="ltr"><head><meta charSet="utf-8" data-next-head=""/><meta name="viewport" content="width=device-width, initial-scale=1" data`
- **P1_readability_md** — `Welcome to the React documentation! This page will give you an introduction to 80% of the React concepts that you will use on a daily basis.  ### You will learn`
- **P2_clean_html_safe** — `<body class="font-text font-medium antialiased text-lg bg-wash dark:bg-wash-dark text-secondary dark:text-secondary-dark leading-base"><link rel="preload" as="i`
- **P2b_clean_html_aggressive** — `<body><link rel="preload" as="image" imagesrcset="/_next/image?url=%2Fimages%2Fuwu.png&amp;w=64&amp;q=75 1x, /_next/image?url=%2Fimages%2Fuwu.png&amp;w=128&amp;`
- **P3_clean_md** — `[React](/)  [v](/versions)  [Learn](/learn)  [Reference](/reference/react)  [Community](/community)  [Blog](/blog)  ### GET STARTED  * [Quick Start](/learn "Qui`
- **P3b_clean_md_aggressive** — `[Learn React](/learn)  # Quick Start  Welcome to the React documentation! This page will give you an introduction to 80% of the React concepts that you will use`
- **P4_trafilatura** — `Welcome to the React documentation! This page will give you an introduction to 80% of the React concepts that you will use on a daily basis.  ### You will learn`

### https://www.alltrails.com/

- **P0_raw** — `<!DOCTYPE html><html lang="en"><head><meta charSet="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/><meta id="Viewport" name="viewp`
- **P1_readability_md** — `Search by city, park, or trail name  Begin typing to search, use the up and down arrow keys to navigate, press enter to select`
- **P2_clean_html_safe** — `<body><div hidden=""></div><header class="styles_header__rA9aY styles_transparent-inverted__2kxGi"><a class="styles_skipToMainContentButton__EpEaT styles_button`
- **P2b_clean_html_aggressive** — `<body><div hidden=""></div><main><main><section aria-label="Hero carousel"><div><div></div><div><h1>Find your next adventure</h1><div><div><div role="search"><d`
- **P3_clean_md** — `[Skip to main content](#main-content)  # Find your next adventure  Search by city, park, or trail name  Begin typing to search, use the up and down arrow keys t`
- **P3b_clean_md_aggressive** — `# Find your next adventure  Search by city, park, or trail name  Begin typing to search, use the up and down arrow keys to navigate, press enter to select  [Exp`
- **P4_trafilatura** — `# Find your next adventure  Search by city, park, or trail name  Begin typing to search, use the up and down arrow keys to navigate, press enter to select  ## T`

