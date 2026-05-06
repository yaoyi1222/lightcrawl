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

| URL (cat) | strat | DOM h_total | Pipeline | Tokens | MD headings | Residue |
|---|---|---:|---|---:|---:|:--:|
| https://en.wikipedia.org/wiki/Claude_Shannon (wiki) | http | 31 | P0_raw | 171224 | 0 | yes |
|  |  |  | P1_readability_md | 31746 | 9 |  |
|  |  |  | P2_clean_html_safe | 150330 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 113374 | 0 |  |
|  |  |  | P3_clean_md | 61959 | 31 |  |
|  |  |  | P3b_clean_md_aggressive | 56365 | 29 |  |
|  |  |  | P4_trafilatura | 27950 | 25 |  |
| https://en.wikipedia.org/wiki/Transformer_(deep_learning_architecture) (wiki) | http | 49 | P0_raw | 233448 | 0 | yes |
|  |  |  | P1_readability_md | 50399 | 19 |  |
|  |  |  | P2_clean_html_safe | 136999 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 100679 | 0 |  |
|  |  |  | P3_clean_md | 52114 | 49 |  |
|  |  |  | P3b_clean_md_aggressive | 47057 | 47 |  |
|  |  |  | P4_trafilatura | 28488 | 36 |  |
| https://docs.python.org/3/library/asyncio.html (static_doc) | http | 9 | P0_raw | 6692 | 0 | yes |
|  |  |  | P1_readability_md | 416 | 1 |  |
|  |  |  | P2_clean_html_safe | 4396 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 2767 | 0 |  |
|  |  |  | P3_clean_md | 1586 | 9 |  |
|  |  |  | P3b_clean_md_aggressive | 1457 | 6 |  |
|  |  |  | P4_trafilatura | 720 | 0 |  |
| https://docs.python.org/3/library/typing.html (static_doc) | http | 42 | P0_raw | 154826 | 0 | yes |
|  |  |  | P1_readability_md | 33963 | 26 |  |
|  |  |  | P2_clean_html_safe | 151203 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 98549 | 0 |  |
|  |  |  | P3_clean_md | 43616 | 42 |  |
|  |  |  | P3b_clean_md_aggressive | 43002 | 38 |  |
|  |  |  | P4_trafilatura | 32709 | 34 |  |
| https://raw.githubusercontent.com/python/cpython/main/README.rst (github_raw) | http | 0 | P0_raw | 2031 | 0 |  |
|  |  |  | P1_readability_md | 1808 | 0 |  |
|  |  |  | P2_clean_html_safe | 2013 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 2013 | 0 |  |
|  |  |  | P3_clean_md | 1808 | 0 |  |
|  |  |  | P3b_clean_md_aggressive | 1808 | 0 |  |
|  |  |  | P4_trafilatura | 0 | 0 |  |
| https://github.com/anthropics/anthropic-sdk-python (github_repo) | http | 35 | P0_raw | 127020 | 0 |  |
|  |  |  | P1_readability_md | 333 | 0 |  |
|  |  |  | P2_clean_html_safe | 31058 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 9755 | 0 |  |
|  |  |  | P3_clean_md | 4010 | 33 |  |
|  |  |  | P3b_clean_md_aggressive | 2332 | 25 |  |
|  |  |  | P4_trafilatura | 207 | 0 |  |
| https://lite.cnn.com/ (news_lite) | http | 0 | P0_raw | 92556 | 0 | yes |
|  |  |  | P1_readability_md | 0 | 0 |  |
|  |  |  | P2_clean_html_safe | 5880 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 5148 | 0 |  |
|  |  |  | P3_clean_md | 4177 | 0 |  |
|  |  |  | P3b_clean_md_aggressive | 4085 | 0 |  |
|  |  |  | P4_trafilatura | 4076 | 0 |  |
| https://react.dev/learn (spa) | http | 16 | P0_raw | 91905 | 0 | yes |
|  |  |  | P1_readability_md | 3317 | 12 | yes |
|  |  |  | P2_clean_html_safe | 30545 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 11826 | 0 |  |
|  |  |  | P3_clean_md | 4066 | 15 | yes |
|  |  |  | P3b_clean_md_aggressive | 3484 | 13 | yes |
|  |  |  | P4_trafilatura | 3110 | 12 | yes |
| https://www.alltrails.com/ (cloudflare_spa) | http | 18 | P0_raw | 113194 | 0 | yes |
|  |  |  | P1_readability_md | 29 | 0 |  |
|  |  |  | P2_clean_html_safe | 12023 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 3574 | 0 |  |
|  |  |  | P3_clean_md | 2167 | 10 |  |
|  |  |  | P3b_clean_md_aggressive | 1603 | 7 |  |
|  |  |  | P4_trafilatura | 77 | 4 |  |
| https://x.com/AnthropicAI (social_x) | http | 1 | P0_raw | 75515 | 0 | yes |
|  |  |  | P1_readability_md | 59 | 0 |  |
|  |  |  | P2_clean_html_safe | 178 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 29 | 0 |  |
|  |  |  | P3_clean_md | 0 | 0 |  |
|  |  |  | P3b_clean_md_aggressive | 0 | 0 |  |
|  |  |  | P4_trafilatura | 76 | 0 |  |
| https://x.com/AnthropicAI/status/1872078117571276867 (social_x_status) | http | 1 | P0_raw | 75081 | 0 | yes |
|  |  |  | P1_readability_md | 59 | 0 |  |
|  |  |  | P2_clean_html_safe | 178 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 29 | 0 |  |
|  |  |  | P3_clean_md | 0 | 0 |  |
|  |  |  | P3b_clean_md_aggressive | 0 | 0 |  |
|  |  |  | P4_trafilatura | 76 | 0 |  |
| https://www.reddit.com/r/MachineLearning/ (social_reddit) | http | 0 | P0_raw | 3231 | 0 | yes |
|  |  |  | P1_readability_md | 0 | 0 |  |
|  |  |  | P2_clean_html_safe | 20 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 17 | 0 |  |
|  |  |  | P3_clean_md | 0 | 0 |  |
|  |  |  | P3b_clean_md_aggressive | 0 | 0 |  |
|  |  |  | P4_trafilatura | 0 | 0 |  |
| https://old.reddit.com/r/MachineLearning/ (social_reddit_old) | browser | 11 | P0_raw | 42500 | 0 | yes |
|  |  |  | P1_readability_md | 67 | 0 |  |
|  |  |  | P2_clean_html_safe | 27769 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 20298 | 0 |  |
|  |  |  | P3_clean_md | 5361 | 2 |  |
|  |  |  | P3b_clean_md_aggressive | 5361 | 2 |  |
|  |  |  | P4_trafilatura | 693 | 0 |  |
| https://www.reddit.com/r/MachineLearning/comments/1f7gvyp/d_what_is_the_state_of_the_art_for_long/ (social_reddit_thread) | http | 0 | P0_raw | 3247 | 0 | yes |
|  |  |  | P1_readability_md | 0 | 0 |  |
|  |  |  | P2_clean_html_safe | 20 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 17 | 0 |  |
|  |  |  | P3_clean_md | 0 | 0 |  |
|  |  |  | P3b_clean_md_aggressive | 0 | 0 |  |
|  |  |  | P4_trafilatura | 0 | 0 |  |
| https://www.anthropic.com/news/claude-3-5-sonnet (anthropic_news) | http | 18 | P0_raw | 45953 | 0 | yes |
|  |  |  | P1_readability_md | 1456 | 5 |  |
|  |  |  | P2_clean_html_safe | 9241 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 2715 | 0 |  |
|  |  |  | P3_clean_md | 2830 | 18 |  |
|  |  |  | P3b_clean_md_aggressive | 1611 | 10 |  |
|  |  |  | P4_trafilatura | 1561 | 9 |  |
| https://www.anthropic.com/research/building-effective-agents (anthropic_research) | http | 28 | P0_raw | 57497 | 0 | yes |
|  |  |  | P1_readability_md | 4317 | 18 |  |
|  |  |  | P2_clean_html_safe | 12853 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 5072 | 0 |  |
|  |  |  | P3_clean_md | 4971 | 28 |  |
|  |  |  | P3b_clean_md_aggressive | 3752 | 20 |  |
|  |  |  | P4_trafilatura | 3532 | 1 |  |
| https://docs.anthropic.com/en/docs/welcome (anthropic_docs) | http | 12 | P0_raw | 212567 | 0 | yes |
|  |  |  | P1_readability_md | 587 | 1 |  |
|  |  |  | P2_clean_html_safe | 17135 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 1760 | 0 |  |
|  |  |  | P3_clean_md | 2780 | 12 |  |
|  |  |  | P3b_clean_md_aggressive | 766 | 4 |  |
|  |  |  | P4_trafilatura | 570 | 0 |  |
| https://docs.anthropic.com/en/docs/build-with-claude/tool-use (anthropic_docs_long) | http | 14 | P0_raw | 225752 | 0 | yes |
|  |  |  | P1_readability_md | 1422 | 1 |  |
|  |  |  | P2_clean_html_safe | 22118 | 0 | yes |
|  |  |  | P2b_clean_html_aggressive | 2936 | 0 |  |
|  |  |  | P3_clean_md | 3564 | 13 |  |
|  |  |  | P3b_clean_md_aggressive | 1557 | 5 |  |
|  |  |  | P4_trafilatura | 1332 | 0 |  |
| https://github.com/anthropics/anthropic-cookbook (github_repo) | http | 38 | P0_raw | 137550 | 0 |  |
|  |  |  | P1_readability_md | 385 | 0 |  |
|  |  |  | P2_clean_html_safe | 34702 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 12453 | 0 |  |
|  |  |  | P3_clean_md | 5756 | 36 |  |
|  |  |  | P3b_clean_md_aggressive | 4070 | 28 |  |
|  |  |  | P4_trafilatura | 883 | 0 |  |
| https://github.com/anthropics/anthropic-cookbook/blob/main/README.md (github_blob) | http | 26 | P0_raw | 107580 | 0 |  |
|  |  |  | P1_readability_md | 385 | 0 |  |
|  |  |  | P2_clean_html_safe | 22231 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 4875 | 0 |  |
|  |  |  | P3_clean_md | 3392 | 25 |  |
|  |  |  | P3b_clean_md_aggressive | 1650 | 16 |  |
|  |  |  | P4_trafilatura | 883 | 0 |  |
| https://stackoverflow.com/questions/231767/what-does-the-yield-keyword-do-in-python (qa_so) | browser | 3 | P0_raw | 11312 | 0 | yes |
|  |  |  | P1_readability_md | 65 | 3 |  |
|  |  |  | P2_clean_html_safe | 302 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 201 | 0 |  |
|  |  |  | P3_clean_md | 87 | 2 |  |
|  |  |  | P3b_clean_md_aggressive | 87 | 2 |  |
|  |  |  | P4_trafilatura | 62 | 2 |  |
| https://news.ycombinator.com/item?id=43000000 (news_hn_thread) | http | 0 | P0_raw | 1355 | 0 |  |
|  |  |  | P1_readability_md | 72 | 0 |  |
|  |  |  | P2_clean_html_safe | 1036 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 858 | 0 |  |
|  |  |  | P3_clean_md | 470 | 0 |  |
|  |  |  | P3b_clean_md_aggressive | 470 | 0 |  |
|  |  |  | P4_trafilatura | 118 | 0 |  |
| https://huggingface.co/blog/llm-course (blog_hf) | http | 8 | P0_raw | 51880 | 0 | yes |
|  |  |  | P1_readability_md | 946 | 5 |  |
|  |  |  | P2_clean_html_safe | 19824 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 11760 | 0 |  |
|  |  |  | P3_clean_md | 1485 | 7 |  |
|  |  |  | P3b_clean_md_aggressive | 1372 | 7 |  |
|  |  |  | P4_trafilatura | 832 | 0 |  |
| https://substack.com/home (spa_substack) | — | — | FETCH FAILED (fetch: FetchError: HTTP_ERROR: Page.goto: net::ERR_CONNECTION_CLOSED at https://) | — | — | — |
| https://medium.com/@karpathy/yes-you-should-understand-backprop-e2f06eab496b (blog_medium) | http | 7 | P0_raw | 51641 | 0 | yes |
|  |  |  | P1_readability_md | 2373 | 6 |  |
|  |  |  | P2_clean_html_safe | 10466 | 0 |  |
|  |  |  | P2b_clean_html_aggressive | 5670 | 0 |  |
|  |  |  | P3_clean_md | 3117 | 6 |  |
|  |  |  | P3b_clean_md_aggressive | 3115 | 6 |  |
|  |  |  | P4_trafilatura | 2205 | 6 |  |

## Aggregate (sum across successful URLs)

| Pipeline | Σ tokens | Σ MD headings | URLs w/ residue |
|---|---:|---:|---:|
| P0_raw | 2095557 | 0 | 19 |
| P1_readability_md | 134204 | 106 | 1 |
| P2_clean_html_safe | 702520 | 0 | 1 |
| P2b_clean_html_aggressive | 416375 | 0 | 0 |
| P3_clean_md | 209316 | 338 | 1 |
| P3b_clean_md_aggressive | 185004 | 265 | 1 |
| P4_trafilatura | 110160 | 129 | 1 |

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
| https://x.com/AnthropicAI | 1 | 0 | 0 | 0 | 0 | 0 | 1 |
| https://x.com/AnthropicAI/status/1872078117571276867 | 1 | 0 | 0 | 0 | 0 | 0 | 1 |
| https://www.reddit.com/r/MachineLearning/ | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| https://old.reddit.com/r/MachineLearning/ | 2 | 9 | 0 | 0 | 0 | 0 | 11 |
| https://www.reddit.com/r/MachineLearning/comments/1f7gvyp/d_what_is_the_state_of_the_art_for_long/ | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| https://www.anthropic.com/news/claude-3-5-sonnet | 1 | 6 | 11 | 0 | 0 | 0 | 18 |
| https://www.anthropic.com/research/building-effective-agents | 1 | 9 | 18 | 0 | 0 | 0 | 28 |
| https://docs.anthropic.com/en/docs/welcome | 1 | 4 | 7 | 0 | 0 | 0 | 12 |
| https://docs.anthropic.com/en/docs/build-with-claude/tool-use | 1 | 4 | 9 | 0 | 0 | 0 | 14 |
| https://github.com/anthropics/anthropic-cookbook | 5 | 17 | 16 | 0 | 0 | 0 | 38 |
| https://github.com/anthropics/anthropic-cookbook/blob/main/README.md | 6 | 14 | 6 | 0 | 0 | 0 | 26 |
| https://stackoverflow.com/questions/231767/what-does-the-yield-keyword-do-in-python | 1 | 2 | 0 | 0 | 0 | 0 | 3 |
| https://news.ycombinator.com/item?id=43000000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| https://huggingface.co/blog/llm-course | 1 | 6 | 1 | 0 | 0 | 0 | 8 |
| https://medium.com/@karpathy/yes-you-should-understand-backprop-e2f06eab496b | 1 | 1 | 5 | 0 | 0 | 0 | 7 |

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
- **P3_clean_md** — `[CNN](/) 5/5/2026  Latest Stories  * [Supreme Court abortion case could force Trump to take a public stance on mifepristone](/2026/05/05/politics/mifepristone-a`
- **P3b_clean_md_aggressive** — `Latest Stories  * [Supreme Court abortion case could force Trump to take a public stance on mifepristone](/2026/05/05/politics/mifepristone-abortion-trump-polit`
- **P4_trafilatura** — `Latest Stories  - [Supreme Court abortion case could force Trump to take a public stance on mifepristone](/2026/05/05/politics/mifepristone-abortion-trump-polit`

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

### https://x.com/AnthropicAI

- **P0_raw** — `<!DOCTYPE html><html dir="ltr" lang="en"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover" /><`
- **P1_readability_md** — `Something went wrong, but don’t fret — let’s give it another shot.  Try again  ![⚠️](https://abs.twimg.com/emoji/v2/svg/26a0.svg) Some privacy related extension`
- **P2_clean_html_safe** — `<body style="background-color: #000000;"><div id="react-root" style="height:100%;display:flex;"><div class="css-175oi2r r-13awgt0 r-12vffkv"><div class="css-175`
- **P2b_clean_html_aggressive** — `<body><div><div><div><div aria-label="Loading…"></div><div></div></div></div></div></body>`
- **P3_clean_md** — ``
- **P3b_clean_md_aggressive** — ``
- **P4_trafilatura** — `We’ve detected that JavaScript is disabled in this browser. Please enable JavaScript or switch to a supported browser to continue using x.com. You can see a lis`

### https://x.com/AnthropicAI/status/1872078117571276867

- **P0_raw** — `<!DOCTYPE html><html dir="ltr" lang="en"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover" /><`
- **P1_readability_md** — `Something went wrong, but don’t fret — let’s give it another shot.  Try again  ![⚠️](https://abs.twimg.com/emoji/v2/svg/26a0.svg) Some privacy related extension`
- **P2_clean_html_safe** — `<body style="background-color: #000000;"><div id="react-root" style="height:100%;display:flex;"><div class="css-175oi2r r-13awgt0 r-12vffkv"><div class="css-175`
- **P2b_clean_html_aggressive** — `<body><div><div><div><div aria-label="Loading…"></div><div></div></div></div></div></body>`
- **P3_clean_md** — ``
- **P3b_clean_md_aggressive** — ``
- **P4_trafilatura** — `We’ve detected that JavaScript is disabled in this browser. Please enable JavaScript or switch to a supported browser to continue using x.com. You can see a lis`

### https://www.reddit.com/r/MachineLearning/

- **P0_raw** — `   <!DOCTYPE html>   <html lang="en">     <head>       <meta charset="UTF-8" />       <meta name="viewport" content="width=device-width, initial-scale=1.0" />  `
- **P1_readability_md** — ``
- **P2_clean_html_safe** — `<body>  <main>  <div class="logo">  </div>  </main>  </body>`
- **P2b_clean_html_aggressive** — `<body>  <main>  <div>  </div>  </main>  </body>`
- **P3_clean_md** — ``
- **P3b_clean_md_aggressive** — ``
- **P4_trafilatura** — ``

### https://old.reddit.com/r/MachineLearning/

- **P0_raw** — `<!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml" lang="en" xml:lang="en" class=" js cssanimations csstransforms"><head><title>Machine Learning</title><`
- **P1_readability_md** — `![](//reddit.com/static/pixel.png)  π Rendered by PID 88 on reddit-service-r2-loggedout-6567c8cd7-vd684 at 2026-05-05 15:40:10.574362+00:00 running 815c875 coun`
- **P2_clean_html_safe** — `<body class="listing-page hot-page"><div id="header" role="banner"><a tabindex="1" href="#content" id="jumpToContent">jump to content</a><div id="sr-header-area`
- **P2b_clean_html_aggressive** — `<body><div role="banner"><a tabindex="1" href="#content">jump to content</a><div><div><div onclick="open_menu(this)"><span>my subreddits</span></div><div><a hre`
- **P3_clean_md** — `[jump to content](#content)  my subreddits  [edit subscriptions](https://old.reddit.com/subreddits/)  * [popular](https://old.reddit.com/r/popular/) * -[all](ht`
- **P3b_clean_md_aggressive** — `[jump to content](#content)  my subreddits  [edit subscriptions](https://old.reddit.com/subreddits/)  * [popular](https://old.reddit.com/r/popular/) * -[all](ht`
- **P4_trafilatura** — `Discussion[[D] Self-Promotion Thread](/r/MachineLearning/comments/1t1d2m0/d_selfpromotion_thread/) ([self.MachineLearning](/r/MachineLearning/))  submitted by [`

### https://www.reddit.com/r/MachineLearning/comments/1f7gvyp/d_what_is_the_state_of_the_art_for_long/

- **P0_raw** — `   <!DOCTYPE html>   <html lang="en">     <head>       <meta charset="UTF-8" />       <meta name="viewport" content="width=device-width, initial-scale=1.0" />  `
- **P1_readability_md** — ``
- **P2_clean_html_safe** — `<body>  <main>  <div class="logo">  </div>  </main>  </body>`
- **P2b_clean_html_aggressive** — `<body>  <main>  <div>  </div>  </main>  </body>`
- **P3_clean_md** — ``
- **P3b_clean_md_aggressive** — ``
- **P4_trafilatura** — ``

### https://www.anthropic.com/news/claude-3-5-sonnet

- **P0_raw** — `<!DOCTYPE html><html lang="en" class="anthropicsans_dce02d96-module__tEBbKW__variable anthropicserif_e7e46c4-module__uImRTq__variable anthropicmono_fae19af3-mod`
- **P1_readability_md** — `* Update    Consumer Terms and Privacy Policy    Aug 28, 2025  Today, we’re launching Claude 3.5 Sonnet—our first release in the forthcoming Claude 3.5 model fa`
- **P2_clean_html_safe** — `<body><div hidden=""><template id="B:0"></template></div><header class="SiteHeader-module-scss-module__zKj4Ca__header" data-theme="light"><div class="SiteHeader`
- **P2b_clean_html_aggressive** — `<body><div hidden=""><template></template></div><main><article><div><div><div><span>Announcements</span></div><h1>Claude 3.5 Sonnet</h1><div>Jun 21, 2024</div><`
- **P3_clean_md** — `[Skip to main content](#main-content)[Skip to footer](#footer)  * [Research](/research) * [Economic Futures](/economic-futures) * * * [News](/news)  [Try Claude`
- **P3b_clean_md_aggressive** — `Announcements  # Claude 3.5 Sonnet  Jun 21, 2024  [Try on Claude.ai](https://claude.ai/)  * Update    Consumer Terms and Privacy Policy    Aug 28, 2025  Today, `
- **P4_trafilatura** — `Consumer Terms and Privacy Policy  Aug 28, 2025   Today, we’re launching Claude 3.5 Sonnet—our first release in the forthcoming Claude 3.5 model family. Claude `

### https://www.anthropic.com/research/building-effective-agents

- **P0_raw** — `<!DOCTYPE html><html lang="en" class="anthropicsans_dce02d96-module__tEBbKW__variable anthropicserif_e7e46c4-module__uImRTq__variable anthropicmono_fae19af3-mod`
- **P1_readability_md** — `Over the past year, we've worked with dozens of teams building large language model (LLM) agents across industries. Consistently, the most successful implementa`
- **P2_clean_html_safe** — `<body><div hidden=""><template id="B:0"></template></div><header class="SiteHeader-module-scss-module__zKj4Ca__header" data-theme="light"><div class="SiteHeader`
- **P2b_clean_html_aggressive** — `<body><div hidden=""><template></template></div><main><section aria-label="Engineering Article Hero"><a href="/engineering">Engineering at Anthropic</a><div><di`
- **P3_clean_md** — `[Skip to main content](#main-content)[Skip to footer](#footer)  * [Research](/research) * [Economic Futures](/economic-futures) * * * [News](/news)  [Try Claude`
- **P3b_clean_md_aggressive** — `[Engineering at Anthropic](/engineering)  # Building effective agents  Published  We've worked with dozens of teams building LLM agents across industries. Consi`
- **P4_trafilatura** — `## Get the developer newsletter  Product updates, how-tos, community spotlights, and more. Delivered monthly to your inbox.  Over the past year, we've worked wi`

### https://docs.anthropic.com/en/docs/welcome

- **P0_raw** — `<!DOCTYPE html><html class="h-screen antialiased bg-bg-100 __variable_8d1da5 __variable_2d8cf6 __variable_5581e8" lang="en-US" data-theme="claude" data-mode="au`
- **P1_readability_md** — `Messages/First steps  Claude is a highly performant, trustworthy, and intelligent AI platform built by Anthropic. Claude excels at tasks involving language, rea`
- **P2_clean_html_safe** — `<body class="bg-bg-100 text-text-100 min-h-screen font-ui"><div hidden=""></div><div role="region" aria-label="Notifications (F8)" tabindex="-1" style="pointer-`
- **P2b_clean_html_aggressive** — `<body><div hidden=""></div><div role="region" aria-label="Notifications (F8)" tabindex="-1"><ol tabindex="-1"></ol></div><template></template><div><div role="st`
- **P3_clean_md** — `Loading...  * [Messages](/docs/en/intro) * [Managed Agents](/docs/en/managed-agents/overview) * [Admin](/docs/en/build-with-claude/administration-api)  Search..`
- **P3b_clean_md_aggressive** — `Loading...  Intro to Claude  Loading...  Loading...  Loading...  Loading...  Loading...  Loading...  Loading...  Loading...  Loading...  Loading...  Loading... `
- **P4_trafilatura** — `MessagesFirst steps  Claude is a highly performant, trustworthy, and intelligent AI platform built by Anthropic. Claude excels at tasks involving language, reas`

### https://docs.anthropic.com/en/docs/build-with-claude/tool-use

- **P0_raw** — `<!DOCTYPE html><html class="h-screen antialiased bg-bg-100 __variable_8d1da5 __variable_2d8cf6 __variable_5581e8" lang="en-US" data-theme="claude" data-mode="au`
- **P1_readability_md** — `Tool use lets Claude call functions you define or that Anthropic provides. Claude decides when to call a tool based on the user's request and the tool's descrip`
- **P2_clean_html_safe** — `<body class="bg-bg-100 text-text-100 min-h-screen font-ui"><div hidden=""></div><div role="region" aria-label="Notifications (F8)" tabindex="-1" style="pointer-`
- **P2b_clean_html_aggressive** — `<body><div hidden=""></div><div role="region" aria-label="Notifications (F8)" tabindex="-1"><ol tabindex="-1"></ol></div><template></template><div><div role="st`
- **P3_clean_md** — `Loading...  * [Messages](/docs/en/intro) * [Managed Agents](/docs/en/managed-agents/overview) * [Admin](/docs/en/build-with-claude/administration-api)  Search..`
- **P3b_clean_md_aggressive** — `Loading...  Overview  Loading...  Loading...  Loading...  Loading...  Loading...  Loading...  Loading...  Loading...  Loading...  Loading...  Loading...  Loadin`
- **P4_trafilatura** — `MessagesTools  Connect Claude to external tools and APIs. Learn where tools execute and how the agentic loop works.  Tool use lets Claude call functions you def`

### https://github.com/anthropics/anthropic-cookbook

- **P0_raw** — `      <!DOCTYPE html> <html   lang="en"      data-color-mode="auto" data-light-theme="light" data-dark-theme="dark"   data-a11y-animated-images="system" data-a1`
- **P1_readability_md** — `The Claude Cookbooks provide code and guides designed to help developers build with Claude, offering copy-able code snippets that you can easily integrate into `
- **P2_clean_html_safe** — `<body class="logged-out env-production page-responsive" style="word-wrap: break-word;">  <div data-turbo-body class="logged-out env-production page-responsive" `
- **P2b_clean_html_aggressive** — `<body>  <div data-turbo-body>  <div role="region" data-turbo-permanent></div>     <div>  <a href="#start-of-content" data-skip-target-assigned="false">Skip to c`
- **P3_clean_md** — `[Skip to content](#start-of-content)  ## Navigation Menu  [Sign in](/login?return_to=https%3A%2F%2Fgithub.com%2Fanthropics%2Fclaude-cookbooks)  Appearance setti`
- **P3b_clean_md_aggressive** — `[Skip to content](#start-of-content)  You signed in with another tab or window. Reload to refresh your session. You signed out in another tab or window. Reload `
- **P4_trafilatura** — `The Claude Cookbooks provide code and guides designed to help developers build with Claude, offering copy-able code snippets that you can easily integrate into `

### https://github.com/anthropics/anthropic-cookbook/blob/main/README.md

- **P0_raw** — `      <!DOCTYPE html> <html   lang="en"      data-color-mode="auto" data-light-theme="light" data-dark-theme="dark"   data-a11y-animated-images="system" data-a1`
- **P1_readability_md** — `The Claude Cookbooks provide code and guides designed to help developers build with Claude, offering copy-able code snippets that you can easily integrate into `
- **P2_clean_html_safe** — `<body class="logged-out env-production page-responsive" style="word-wrap: break-word;">  <div data-turbo-body class="logged-out env-production page-responsive" `
- **P2b_clean_html_aggressive** — `<body>  <div data-turbo-body>  <div role="region" data-turbo-permanent></div>     <div>  <a href="#start-of-content" data-skip-target-assigned="false">Skip to c`
- **P3_clean_md** — `[Skip to content](#start-of-content)  ## Navigation Menu  [Sign in](/login?return_to=https%3A%2F%2Fgithub.com%2Fanthropics%2Fclaude-cookbooks%2Fblob%2Fmain%2FRE`
- **P3b_clean_md_aggressive** — `[Skip to content](#start-of-content)  You signed in with another tab or window. Reload to refresh your session. You signed out in another tab or window. Reload `
- **P4_trafilatura** — `The Claude Cookbooks provide code and guides designed to help developers build with Claude, offering copy-able code snippets that you can easily integrate into `

### https://stackoverflow.com/questions/231767/what-does-the-yield-keyword-do-in-python

- **P0_raw** — `<!DOCTYPE html><html lang="en-US" dir="ltr"><head><title>Just a moment...</title><meta http-equiv="Content-Type" content="text/html; charset=UTF-8"><meta http-e`
- **P1_readability_md** — `![Icon for stackoverflow.com](/favicon.ico)  # stackoverflow.com  ## Performing security verification  This website uses a security service to protect against m`
- **P2_clean_html_safe** — `<body><div class="main-wrapper lang-en-us" role="main"><div class="main-content"><div class="ch-title-zone"><h1>stackoverflow.com</h1></div><h2 id="Eedwz2" clas`
- **P2b_clean_html_aggressive** — `<body><div role="main"><div><div><h1>stackoverflow.com</h1></div><h2>Performing security verification</h2><p>This website uses a security service to protect aga`
- **P3_clean_md** — `# stackoverflow.com  ## Performing security verification  This website uses a security service to protect against malicious bots. This page is displayed while t`
- **P3b_clean_md_aggressive** — `# stackoverflow.com  ## Performing security verification  This website uses a security service to protect against malicious bots. This page is displayed while t`
- **P4_trafilatura** — `# stackoverflow.com  ## Performing security verification  This website uses a security service to protect against malicious bots. This page is displayed while t`

### https://news.ycombinator.com/item?id=43000000

- **P0_raw** — `<html lang="en" op="item"><head><meta name="referrer" content="origin"><meta name="viewport" content="width=device-width, initial-scale=1.0"><link rel="styleshe`
- **P1_readability_md** — `It doesn't have to be black/white, either/or.  The US can afford to feed everyone and still not be 'Socialist'.  I think you are confusing 'Capitalism' with 'Cr`
- **P2_clean_html_safe** — `<body><center><table id="hnmain" border="0" cellpadding="0" cellspacing="0" width="85%" bgcolor="#f6f6ef"><tr><td bgcolor="#ff6600"><table border="0" cellpaddin`
- **P2b_clean_html_aggressive** — `<body><center><table border="0" cellpadding="0" cellspacing="0" width="85%" bgcolor="#f6f6ef"><tr><td bgcolor="#ff6600"><table border="0" cellpadding="0" cellsp`
- **P3_clean_md** — `|  |  |  |  | | --- | --- | --- | --- | | |  |  |  | | --- | --- | --- | |  | **[Hacker News](news)**[new](newest) | [past](front) | [comments](newcomments) | <`
- **P3b_clean_md_aggressive** — `|  |  |  |  | | --- | --- | --- | --- | | |  |  |  | | --- | --- | --- | |  | **[Hacker News](news)**[new](newest) | [past](front) | [comments](newcomments) | <`
- **P4_trafilatura** — `The US can afford to feed everyone and still not be 'Socialist'.  I think you are confusing 'Capitalism' with 'Cruelty'. What if I were to tell you, you don't h`

### https://huggingface.co/blog/llm-course

- **P0_raw** — `<!doctype html> <html class=""> 	<head> 		<meta charset="utf-8" />  		<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no" />`
- **P1_readability_md** — `# The NLP Course is becoming the LLM Course!  [![image/gif](https://cdn-uploads.huggingface.co/production/uploads/62d648291fa3e4e7ae3fa6e8/I6Pq5TftMqjLOqZzKNplg`
- **P2_clean_html_safe** — `<body class="flex flex-col min-h-dvh bg-white dark:bg-gray-950 text-black BlogPage">  <div class="flex min-h-dvh flex-col"><div class="SVELTE_HYDRATER contents"`
- **P2b_clean_html_aggressive** — `<body>  <div><div data-target="ClientErrorCatcher" data-props="{}"></div> <div data-target="DeviceProvider" data-props="{}"></div> <div data-target="SystemTheme`
- **P3_clean_md** — `[Hugging Face](/)  * [new](/storage)  * [Pricing](/pricing) * --- * [Log In](/login) * [Sign Up](/join)  # The NLP Course is becoming the LLM Course!  Published`
- **P3b_clean_md_aggressive** — `# The NLP Course is becoming the LLM Course!  Published April 3, 2025  [Update on GitHub](https://github.com/huggingface/blog/blob/main/llm-course.md)  [106](/l`
- **P4_trafilatura** — `# [ ](#the-nlp-course-is-becoming-the-llm-course) The NLP Course is becoming the LLM Course!  [Update on GitHub](https://github.com/huggingface/blog/blob/main/l`

### https://medium.com/@karpathy/yes-you-should-understand-backprop-e2f06eab496b

- **P0_raw** — `<!doctype html><html lang="en"><head><title data-rh="true">Yes you should understand backprop | by Andrej Karpathy | Medium</title><meta data-rh="true" charset=`
- **P1_readability_md** — `# Yes you should understand backprop  When we offered [CS231n](http://cs231n.stanford.edu/) (Deep Learning class) at Stanford, we intentionally designed the pro`
- **P2_clean_html_safe** — `<body><div id="root"><div class="a b c"><a href="/sitemap/sitemap.xml" class="d">Sitemap</a><div class="e c"><div class="e f g h c"><div class="i j k l m n o p `
- **P2b_clean_html_aggressive** — `<body><div><div><a href="/sitemap/sitemap.xml">Sitemap</a><div><div><div><a href="https://play.google.com/store/apps/details?id=com.medium.reader&amp;referrer=u`
- **P3_clean_md** — `[Sitemap](/sitemap/sitemap.xml)  [Open in app](https://play.google.com/store/apps/details?id=com.medium.reader&referrer=utm_source%3DmobileNavBar&source=post_pa`
- **P3b_clean_md_aggressive** — `[Sitemap](/sitemap/sitemap.xml)  [Open in app](https://play.google.com/store/apps/details?id=com.medium.reader&referrer=utm_source%3DmobileNavBar&source=post_pa`
- **P4_trafilatura** — `# Yes you should understand backprop  When we offered [CS231n](http://cs231n.stanford.edu/) (Deep Learning class) at Stanford, we intentionally designed the pro`

